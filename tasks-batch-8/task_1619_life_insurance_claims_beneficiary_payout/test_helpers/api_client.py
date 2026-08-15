"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving logical clock ---
    def set_logical_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- State statutes ---
    def create_state_statute(self, payload, headers):
        return self._request("POST", "/state-statutes", payload, headers)

    def list_state_statutes(self, headers, params=None):
        return self._request("GET", "/state-statutes", headers=headers, params=params)

    # --- Policies ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def lapse_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/lapse", {}, headers)

    # --- Beneficiary designations ---
    def create_beneficiary_designation(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/beneficiary-designations", payload, headers)

    def list_beneficiary_designations(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/beneficiary-designations",
                             headers=headers, params=params)

    def revoke_beneficiary_designation(self, designation_id, headers):
        return self._request(
            "POST", f"/beneficiary-designations/{designation_id}/revoke", {}, headers)

    # --- Claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def begin_review(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/begin-review", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    def rescind_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/rescind", payload, headers)

    def refer_interpleader(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/refer-interpleader",
                             payload, headers)

    def execute_payment(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/execute-payment", {}, headers)

    # --- Death documents ---
    def upload_document(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/documents", payload, headers)

    def list_documents(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/documents",
                             headers=headers, params=params)

    def review_document(self, claim_id, document_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/documents/{document_id}/review", payload, headers)

    # --- Beneficiary claims ---
    def file_beneficiary_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/beneficiary-claims",
                             payload, headers)

    def list_claim_beneficiary_claims(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/beneficiary-claims",
                             headers=headers, params=params)

    def list_beneficiary_claims(self, headers, params=None):
        return self._request("GET", "/beneficiary-claims", headers=headers, params=params)

    def get_beneficiary_claim(self, beneficiary_claim_id, headers):
        return self._request("GET", f"/beneficiary-claims/{beneficiary_claim_id}",
                             headers=headers)

    def validate_beneficiary_claim(self, beneficiary_claim_id, headers):
        return self._request(
            "POST", f"/beneficiary-claims/{beneficiary_claim_id}/validate", {}, headers)

    def reject_beneficiary_claim(self, beneficiary_claim_id, payload, headers):
        return self._request(
            "POST", f"/beneficiary-claims/{beneficiary_claim_id}/reject", payload, headers)

    def withdraw_beneficiary_claim(self, beneficiary_claim_id, headers):
        return self._request(
            "POST", f"/beneficiary-claims/{beneficiary_claim_id}/withdraw", {}, headers)

    # --- Payout elections ---
    def create_payout_election(self, beneficiary_claim_id, payload, headers):
        return self._request(
            "POST", f"/beneficiary-claims/{beneficiary_claim_id}/elections",
            payload, headers)

    def list_payout_elections(self, beneficiary_claim_id, headers, params=None):
        return self._request("GET", f"/beneficiary-claims/{beneficiary_claim_id}/elections",
                             headers=headers, params=params)

    def confirm_payout_election(self, election_id, headers):
        return self._request("POST", f"/payout-elections/{election_id}/confirm", {}, headers)

    # --- Retained asset accounts ---
    def list_retained_asset_accounts(self, headers, params=None):
        return self._request("GET", "/retained-asset-accounts", headers=headers,
                             params=params)

    def get_retained_asset_account(self, account_id, headers):
        return self._request("GET", f"/retained-asset-accounts/{account_id}",
                             headers=headers)

    def withdraw_from_account(self, account_id, payload, headers):
        return self._request("POST", f"/retained-asset-accounts/{account_id}/withdrawals",
                             payload, headers)

    # --- Death master matches ---
    def create_death_master_match(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/death-master-matches",
                             payload, headers)

    def list_death_master_matches(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/death-master-matches",
                             headers=headers, params=params)

    def review_death_master_match(self, match_id, payload, headers):
        return self._request("POST", f"/death-master-matches/{match_id}/review",
                             payload, headers)

    # --- Escheatment cases ---
    def list_escheatment_cases(self, headers, params=None):
        return self._request("GET", "/escheatment-cases", headers=headers, params=params)

    def get_escheatment_case(self, case_id, headers):
        return self._request("GET", f"/escheatment-cases/{case_id}", headers=headers)

    def resolve_escheatment_case(self, case_id, payload, headers):
        return self._request("POST", f"/escheatment-cases/{case_id}/resolve",
                             payload, headers)

    def escheat_escheatment_case(self, case_id, headers):
        return self._request("POST", f"/escheatment-cases/{case_id}/escheat", {}, headers)


api_client = ApiClient()
