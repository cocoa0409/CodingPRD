"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Plan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def terminate_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/terminate", payload, headers)

    def close_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/close", {}, headers)

    # ---- Provider ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def terminate_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/terminate", payload, headers)

    # ---- StopLossPolicy ----
    def create_stop_loss_policy(self, payload, headers):
        return self._request("POST", "/stop-loss-policies", payload, headers)

    def get_stop_loss_policy(self, policy_id, headers):
        return self._request("GET", f"/stop-loss-policies/{policy_id}", headers=headers)

    def list_stop_loss_policies(self, headers, params=None):
        return self._request("GET", "/stop-loss-policies", headers=headers, params=params)

    def activate_stop_loss_policy(self, policy_id, headers):
        return self._request("POST", f"/stop-loss-policies/{policy_id}/activate", {}, headers)

    def settle_aggregate(self, policy_id, headers):
        return self._request("POST", f"/stop-loss-policies/{policy_id}/settle-aggregate", {}, headers)

    # ---- Laser ----
    def create_laser(self, payload, headers):
        return self._request("POST", "/lasers", payload, headers)

    def get_laser(self, laser_id, headers):
        return self._request("GET", f"/lasers/{laser_id}", headers=headers)

    def list_lasers(self, headers, params=None):
        return self._request("GET", "/lasers", headers=headers, params=params)

    # ---- Claim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/adjudicate", {}, headers)

    def pend_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/pend", {}, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    def reverse_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/reverse", {}, headers)

    # ---- FundAccount ----
    def create_fund_account(self, payload, headers):
        return self._request("POST", "/fund-accounts", payload, headers)

    def get_fund_account(self, fund_account_id, headers):
        return self._request("GET", f"/fund-accounts/{fund_account_id}", headers=headers)

    def list_fund_accounts(self, headers, params=None):
        return self._request("GET", "/fund-accounts", headers=headers, params=params)

    def deposit_fund_account(self, fund_account_id, payload, headers):
        return self._request("POST", f"/fund-accounts/{fund_account_id}/deposit", payload, headers)

    # ---- CheckRun ----
    def create_check_run(self, payload, headers):
        return self._request("POST", "/check-runs", payload, headers)

    def get_check_run(self, check_run_id, headers):
        return self._request("GET", f"/check-runs/{check_run_id}", headers=headers)

    def list_fund_account_check_runs(self, fund_account_id, headers, params=None):
        return self._request("GET", f"/fund-accounts/{fund_account_id}/check-runs", headers=headers, params=params)

    def release_check_run(self, check_run_id, payload, headers):
        return self._request("POST", f"/check-runs/{check_run_id}/release", payload, headers)

    def void_check_run(self, check_run_id, headers):
        return self._request("POST", f"/check-runs/{check_run_id}/void", {}, headers)

    # ---- StopLossReimbursement ----
    def get_reimbursement(self, reimbursement_id, headers):
        return self._request("GET", f"/stop-loss-reimbursements/{reimbursement_id}", headers=headers)

    def list_reimbursements(self, headers, params=None):
        return self._request("GET", "/stop-loss-reimbursements", headers=headers, params=params)

    # ---- Form1099 ----
    def generate_form_1099(self, payload, headers):
        return self._request("POST", "/form-1099s/generate", payload, headers)

    def get_form_1099(self, form_id, headers):
        return self._request("GET", f"/form-1099s/{form_id}", headers=headers)

    def list_form_1099s(self, headers, params=None):
        return self._request("GET", "/form-1099s", headers=headers, params=params)

    # ---- Clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
