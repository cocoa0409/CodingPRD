"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Plans ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/v1/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/v1/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/v1/plans/{plan_id}", headers=headers)

    def freeze_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/freeze", {}, headers)

    def unfreeze_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/unfreeze", {}, headers)

    def terminate_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/terminate", {}, headers)

    def create_freeze_window(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/freeze-windows", payload, headers)

    def list_freeze_windows(self, plan_id, headers, params=None):
        return self._request("GET", f"/v1/plans/{plan_id}/freeze-windows", headers=headers, params=params)

    # --- Participants ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/v1/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/v1/participants/{participant_id}", headers=headers)

    # --- Accounts & money sources ---
    def create_account(self, payload, headers):
        return self._request("POST", "/v1/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/v1/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/v1/accounts/{account_id}", headers=headers)

    def list_source_balances(self, account_id, headers, params=None):
        return self._request("GET", f"/v1/accounts/{account_id}/source-balances", headers=headers, params=params)

    def list_account_redeposits(self, account_id, headers, params=None):
        return self._request("GET", f"/v1/accounts/{account_id}/redeposits", headers=headers, params=params)

    # --- Loans ---
    def create_loan(self, account_id, payload, headers):
        return self._request("POST", f"/v1/accounts/{account_id}/loans", payload, headers)

    def list_account_loans(self, account_id, headers, params=None):
        return self._request("GET", f"/v1/accounts/{account_id}/loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/v1/loans/{loan_id}", headers=headers)

    def list_loan_redeposits(self, loan_id, headers, params=None):
        return self._request("GET", f"/v1/loans/{loan_id}/redeposits", headers=headers, params=params)

    def transfer_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/v1/loans/{loan_id}/transfer", payload, headers)

    def offset_loan(self, loan_id, headers):
        return self._request("POST", f"/v1/loans/{loan_id}/offset", {}, headers)

    # --- Rollover cases ---
    def create_rollover_case(self, payload, headers):
        return self._request("POST", "/v1/rollover-cases", payload, headers)

    def list_rollover_cases(self, headers, params=None):
        return self._request("GET", "/v1/rollover-cases", headers=headers, params=params)

    def get_rollover_case(self, case_id, headers):
        return self._request("GET", f"/v1/rollover-cases/{case_id}", headers=headers)

    def amend_rollover_case(self, case_id, payload, headers):
        return self._request("PATCH", f"/v1/rollover-cases/{case_id}", payload, headers)

    def submit_case(self, case_id, headers):
        return self._request("POST", f"/v1/rollover-cases/{case_id}/submit", {}, headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/v1/rollover-cases/{case_id}/cancel", {}, headers)

    def decide_eligibility(self, case_id, payload, headers):
        return self._request("POST", f"/v1/rollover-cases/{case_id}/decide-eligibility", payload, headers)

    def assemble_disbursement(self, case_id, payload, headers):
        return self._request("POST", f"/v1/rollover-cases/{case_id}/issue-disbursement", payload, headers)

    def confirm_receipt(self, case_id, headers):
        return self._request("POST", f"/v1/rollover-cases/{case_id}/confirm-receipt", {}, headers)

    def execute_transfer(self, case_id, headers):
        return self._request("POST", f"/v1/rollover-cases/{case_id}/execute-transfer", {}, headers)

    def execute_conversion(self, case_id, headers):
        return self._request("POST", f"/v1/rollover-cases/{case_id}/execute-conversion", {}, headers)

    def post_credit(self, case_id, payload, headers):
        return self._request("POST", f"/v1/rollover-cases/{case_id}/post-credit", payload, headers)

    def create_case_verification(self, case_id, payload, headers):
        return self._request("POST", f"/v1/rollover-cases/{case_id}/verifications", payload, headers)

    # --- Case sub-resources ---
    def list_case_documents(self, case_id, headers, params=None):
        return self._request("GET", f"/v1/rollover-cases/{case_id}/documents", headers=headers, params=params)

    def list_case_disbursements(self, case_id, headers, params=None):
        return self._request("GET", f"/v1/rollover-cases/{case_id}/disbursements", headers=headers, params=params)

    def list_case_redeposits(self, case_id, headers, params=None):
        return self._request("GET", f"/v1/rollover-cases/{case_id}/redeposits", headers=headers, params=params)

    def list_case_verifications(self, case_id, headers, params=None):
        return self._request("GET", f"/v1/rollover-cases/{case_id}/verifications", headers=headers, params=params)

    def list_case_notices(self, case_id, headers, params=None):
        return self._request("GET", f"/v1/rollover-cases/{case_id}/notices", headers=headers, params=params)

    # --- Documents & verifications ---
    def submit_document(self, doc_id, headers):
        return self._request("POST", f"/v1/documents/{doc_id}/submit", {}, headers)

    def review_document(self, doc_id, payload, headers):
        return self._request("POST", f"/v1/documents/{doc_id}/review", payload, headers)

    def complete_verification(self, ver_id, payload, headers):
        return self._request("POST", f"/v1/verifications/{ver_id}/complete", payload, headers)

    # --- Disbursements ---
    def issue_disbursement(self, disb_id, headers):
        return self._request("POST", f"/v1/disbursements/{disb_id}/issue", {}, headers)

    def cancel_disbursement(self, disb_id, headers):
        return self._request("POST", f"/v1/disbursements/{disb_id}/cancel", {}, headers)

    def return_disbursement(self, disb_id, headers):
        return self._request("POST", f"/v1/disbursements/{disb_id}/return", {}, headers)

    def reissue_disbursement(self, disb_id, headers):
        return self._request("POST", f"/v1/disbursements/{disb_id}/reissue", {}, headers)

    # --- Redeposits ---
    def create_redeposit(self, payload, headers):
        return self._request("POST", "/v1/redeposits", payload, headers)

    def credit_redeposit(self, red_id, headers):
        return self._request("POST", f"/v1/redeposits/{red_id}/credit", {}, headers)

    def reject_redeposit(self, red_id, headers):
        return self._request("POST", f"/v1/redeposits/{red_id}/reject", {}, headers)

    # --- Tax forms ---
    def list_tax_forms(self, headers, params=None):
        return self._request("GET", "/v1/tax-forms", headers=headers, params=params)

    def get_tax_form(self, form_id, headers):
        return self._request("GET", f"/v1/tax-forms/{form_id}", headers=headers)

    def finalize_tax_form(self, form_id, headers):
        return self._request("POST", f"/v1/tax-forms/{form_id}/finalize", {}, headers)

    def correct_tax_form(self, form_id, payload, headers):
        return self._request("POST", f"/v1/tax-forms/{form_id}/correct", payload, headers)

    # --- Operations ---
    def run_daily_sweep(self, headers):
        return self._request("POST", "/v1/sweeps/daily", {}, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
