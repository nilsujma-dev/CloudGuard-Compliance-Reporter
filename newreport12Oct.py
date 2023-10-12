import argparse
import requests
import base64
import pandas as pd
import openpyxl
import io
import os

def main():
    parser = argparse.ArgumentParser(description="Script to process CLI arguments")
    
    parser.add_argument("--username", required=True, help="Username for authentication")
    parser.add_argument("--password", required=True, help="Password for authentication")
    parser.add_argument("--platform", required=True, help="Please give platform: Aws, Azure, Google, Kubernetes")
    parser.add_argument("--account_name", required=True, help="Provide Cloud Account Name, Azure Subscription, Google Project or Cluster Name. If your account name or cluster has space. please use duuble quote before input")
    parser.add_argument("--entityname", required=True, help="Provide a comma-separated list of entity names")
    
    args = parser.parse_args()
    
    username = args.username
    password = args.password
    platform = args.platform.lower()
    account_name = args.account_name
    entityname = [entity.strip() for entity in args.entityname.split(',')]
    print("Username:", username)
    print("Platform:", platform)
    print("Cloud Account Name:", account_name)
    print("Entity Names:", entityname)
    
    headers = get_headers(username, password)
    desired_id, org_unit_path = get_cloud_account_id(account_name, platform, headers)
    print (org_unit_path)
    bundleid = get_bundle_id(platform)
    
    payload = {
        "cloudAccountBundleFilters": [
            {
                "bundleIds": [bundleid],
                "cloudAccountIds": [desired_id],
                "cloudAccountType": platform
            }
        ]
    }
    valid_entities = [entity for entity in entityname if check_assets(headers, entity,desired_id)]
    invalid_entities = [entity for entity in entityname if entity not in valid_entities]
    #file input path and name
    filename = 'flattened_data9Octver5.xlsx'
    assessment_df = pd.DataFrame()  # Create an empty DataFrame for 'Assessment Results'
    invalid_df = pd.DataFrame()  # Create an empty DataFrame for 'Invalid Entities' 
    # Check if the file exists
    if os.path.isfile(filename):
        # If the file exists, load its content into DataFrames
        with pd.ExcelFile(filename) as xls:
            if 'Assessment Results' in xls.sheet_names:
                assessment_df = pd.read_excel(xls, 'Assessment Results')
            if 'Invalid Entities' in xls.sheet_names:
                invalid_df = pd.read_excel(xls, 'Invalid Entities')

    # Update the DataFrames with new data
    if valid_entities:
        assessment_df = get_assessment_result(payload, headers, org_unit_path, valid_entities, account_name)
    if invalid_entities:
        new_invalid_df = pd.DataFrame({
            'Entity Name': invalid_entities,
            'Description': ["This resource cannot be found in your cloud account or cluster. Please check the name of the entity and verify if the asset is provisioned."] * len(invalid_entities)
        })
        invalid_df = new_invalid_df

    # Write the DataFrames to the Excel file
    with pd.ExcelWriter(filename, engine='openpyxl', mode='w') as writer:
        assessment_df.to_excel(writer, sheet_name='Assessment Results', index=False)
        invalid_df.to_excel(writer, sheet_name='Invalid Entities', index=False)

#function to check entity is exist in account or cluster
def check_assets (headers,entityname, desired_id):
    check_url = "https://api.dome9.com/v2/protected-asset/search"
    payload = { "filter": { "fields": [
            {
                "name": "cloudAccountId",
                "value": desired_id
            },
            {
                "name": "name",
                "value": entityname
            }
        ] } }
    check_result = requests.post(check_url, json=payload, headers=headers)
    # Check if the assets list in the response is not empty
    if check_result.status_code == 201 and check_result.json().get('assets'):
        return True
    return False

#function to create get header with username and password from CLI
def get_headers(username, password):
    credentials = f"{username}:{password}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    headers = {
        "accept": "application/json",
        "authorization": f"Basic {encoded_credentials}"
    }
    return headers

#function to select API based on cloud platform
def get_cloud_account_id(account_name, platform, headers):
    # Determine URL based on the platform
    if platform == "aws":
        url = "https://api.dome9.com/v2/CloudAccounts"
    elif platform == "azure":
        url = "https://api.dome9.com/v2/AzureCloudAccount"
    elif platform == "google":
        url = "https://api.dome9.com/v2/GoogleCloudAccount"
    elif platform == "kubernetes":
        url = "https://api.dome9.com/v2/kubernetes/account"
    else:
        raise ValueError("Unsupported platform!")
    response = requests.get(url, headers=headers)
    response.raise_for_status()  # Check for HTTP errors
    json_response = response.json()
    return find_id_by_account_name(json_response, account_name)

#function to select ruleset id based on platform. Need to update if we change any new ruleset for SCB
def get_bundle_id(platform):
    platform_bundles = {
        "aws": 902486,
        "azure": 902546,
        "google": -128,
        "kubernetes": -72
    }
    return platform_bundles.get(platform)
class AccountNameNotFoundError(Exception):
    """Raised when the account name is not found in the response."""
    pass

#function to find cloud id and org unit path by using cloud account name
def find_id_by_account_name(json_response, account_name):
    for item in json_response:
        if item.get("name", "").lower() == account_name.lower():
            account_id = item.get("id")
            org_unit_path = item.get("organizationalUnitPath", None)
            return account_id, org_unit_path

    # If the loop completes without finding the account name, raise an error.
    raise AccountNameNotFoundError(f"Account name '{account_name}' not found in the system.")

#function to get assessment as json format and filter by entityname
def get_assessment_result(payload, headers, org_unit_path,entityname,account_name):
    assessment_url = "https://api.dome9.com/v2/AssessmentHistoryV2/LastAssessmentResults"
    assessment_response = requests.post(assessment_url, json=payload, headers=headers)
    print("Entity Names from CLI:", entityname)
    if assessment_response.status_code != 200:
        print(f"Error: {assessment_response.status_code}")
        print(assessment_response.text)
        exit()
    data_list = assessment_response.json()
    flattened_data = []
    entityname_set = set([e.lower() for e in entityname])
    for data in data_list:
        request = data.get('request', [])
        for test in data.get('tests', []):
            rule = test.get('rule', {})
            for entity in test.get('entityResults', []):
                test_obj = entity.get('testObj', {})
                # Check if any entity from entityname is contained in testObj['id']
                matched_entity = next((entity for entity in entityname_set if entity in test_obj.get('id').lower()), None)
                if matched_entity:

                    flattened_data.append({
                        'Organization Unit Path' : org_unit_path,
                        'Cloud Account' : account_name,
                        'Ruleset Name': request.get('name'),
                        'Category' : rule.get('category'),
                        'Severity': rule.get('severity'),
                        'Compliance Section' : rule.get('complianceTag'),
                        'Entity Type': test_obj.get('entityType'),
                        'Entity Name' : matched_entity,
                        'Entity ID': test_obj.get('id'),
                        'Rule Name': rule.get('name'),
                        'Rule Description': rule.get('description'),
                        'Remediation' : rule.get('remediation'),
                        'Test Result' : test.get('testPassed'),
                        'Exclude' : entity.get('isExcluded'),
                        'Create Time' : data.get('createdTime')
                        })
                    # Remove the matched entity from the set.
                    entityname_set.remove(matched_entity)
    if entityname_set:
        for unmatched_entity in entityname_set:
            flattened_data.append({
                'Organization Unit Path': org_unit_path,
                'Cloud Account' : account_name,
                'Ruleset Name': 'N/A',
                'Category' : 'N/A',
                'Severity': 'N/A',
                'Compliance Section' : 'N/A',
                'Entity Type': 'N/A',
                'Entity Name' : unmatched_entity,
                'Entity ID': 'N/A',
                'Rule Name': 'N/A',
                'Rule Description': 'This entity name already passed compliance',
                'Remediation' : 'N/A',
                'Test Result' : True,
                'Exclude' : False,
                'Create Time' : data.get('createdTime')
            
            })

    df = pd.DataFrame(flattened_data)
    return df
if __name__ == "__main__":
    main()





