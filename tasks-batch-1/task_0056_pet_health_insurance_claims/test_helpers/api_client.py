"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Accounts ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers=headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    # ---- Policies (nested) ----
    def create_policy(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/policies", payload, headers=headers)

    def list_policies_of_account(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/policies", headers=headers, params=params)

    def get_policy_nested(self, account_id, policy_id, headers):
        return self._request("GET", f"/accounts/{account_id}/policies/{policy_id}", headers=headers)

    def activate_policy(self, account_id, policy_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/policies/{policy_id}/activate", payload, headers=headers)

    def lapse_policy(self, account_id, policy_id, headers):
        return self._request("POST", f"/accounts/{account_id}/policies/{policy_id}/lapse", {}, headers=headers)

    def cancel_policy(self, account_id, policy_id, headers):
        return self._request("POST", f"/accounts/{account_id}/policies/{policy_id}/cancel", {}, headers=headers)

    def list_policy_years(self, account_id, policy_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/policies/{policy_id}/policy-years", headers=headers, params=params)

    # ---- Conditions ----
    def create_condition(self, account_id, policy_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/policies/{policy_id}/conditions", payload, headers=headers)

    def list_conditions_of_policy(self, account_id, policy_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/policies/{policy_id}/conditions", headers=headers, params=params)

    # ---- Claims ----
    def create_claim(self, account_id, policy_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/policies/{policy_id}/claims", payload, headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def create_line(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/lines", payload, headers=headers)

    def list_lines(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/lines", headers=headers, params=params)

    def patch_line(self, claim_id, line_id, payload, headers):
        return self._request("PATCH", f"/claims/{claim_id}/lines/{line_id}", payload, headers=headers)

    def create_invoice(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/invoices", payload, headers=headers)

    def list_invoices(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/invoices", headers=headers, params=params)

    def run_ocr(self, claim_id, invoice_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/invoices/{invoice_id}/run-ocr", payload, headers=headers)

    def accept_invoice(self, claim_id, invoice_id, headers):
        return self._request("POST", f"/claims/{claim_id}/invoices/{invoice_id}/accept", {}, headers=headers)

    def reject_invoice(self, claim_id, invoice_id, headers):
        return self._request("POST", f"/claims/{claim_id}/invoices/{invoice_id}/reject", {}, headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/submit", {}, headers=headers)

    def begin_review(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/begin-review", {}, headers=headers)

    def adjudicate(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/adjudicate", payload, headers=headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/pay", {}, headers=headers)

    def reverse_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/reverse", payload, headers=headers)

    # ---- Flat fetch / filtered list endpoints ----
    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def get_policy_year(self, year_id, headers):
        return self._request("GET", f"/policy-years/{year_id}", headers=headers)

    def list_policy_years_flat(self, headers, params=None):
        return self._request("GET", "/policy-years", headers=headers, params=params)

    def get_condition(self, condition_id, headers):
        return self._request("GET", f"/conditions/{condition_id}", headers=headers)

    def list_conditions(self, headers, params=None):
        return self._request("GET", "/conditions", headers=headers, params=params)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/claim-lines/{line_id}", headers=headers)

    def list_claim_lines(self, headers, params=None):
        return self._request("GET", "/claim-lines", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices_flat(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    # ---- Test clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
