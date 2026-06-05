"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Participants ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def update_participant(self, participant_id, payload, headers):
        return self._request("PATCH", f"/participants/{participant_id}", payload, headers)

    # --- Plan years ---
    def create_plan_year(self, payload, headers):
        return self._request("POST", "/plan-years", payload, headers)

    def get_plan_year(self, plan_year_id, headers):
        return self._request("GET", f"/plan-years/{plan_year_id}", headers=headers)

    def list_plan_years(self, headers, params=None):
        return self._request("GET", "/plan-years", headers=headers, params=params)

    def settle_plan_year(self, plan_year_id, headers, payload=None):
        return self._request("POST", f"/plan-years/{plan_year_id}/settle",
                             payload if payload is not None else {}, headers)

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def activate_account(self, account_id, headers, payload=None):
        return self._request("POST", f"/accounts/{account_id}/activate",
                             payload if payload is not None else {}, headers)

    def clear_hold(self, account_id, headers, payload=None):
        return self._request("POST", f"/accounts/{account_id}/clear-hold",
                             payload if payload is not None else {}, headers)

    def create_contribution(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/contributions", payload, headers)

    def list_contributions(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/contributions",
                             headers=headers, params=params)

    def reverse_contribution(self, account_id, contribution_id, payload, headers):
        return self._request(
            "POST",
            f"/accounts/{account_id}/contributions/{contribution_id}/reverse",
            payload, headers,
        )

    def get_account_ledger_entries(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/ledger-entries",
                             headers=headers, params=params)

    # --- Claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/adjudicate", payload, headers)

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/resubmit", payload, headers)

    def void_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/void",
                             payload if payload is not None else {}, headers)

    def get_claim_ledger_entries(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/ledger-entries",
                             headers=headers, params=params)

    # --- Reimbursement batches ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/reimbursement-batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/reimbursement-batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/reimbursement-batches", headers=headers, params=params)

    def disburse_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/reimbursement-batches/{batch_id}/disburse", payload, headers)

    # --- Test clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
