"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
envelope, headers, and HTTP plumbing. All endpoint paths are mounted at the
API root.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Company ----
    def create_company(self, payload, headers):
        return self._request("POST", "/companies", payload, headers)

    def get_company(self, company_id, headers):
        return self._request("GET", f"/companies/{company_id}", headers=headers)

    def list_companies(self, headers, params=None):
        return self._request("GET", "/companies", headers=headers, params=params)

    def suspend_company(self, company_id, payload, headers):
        return self._request("POST", f"/companies/{company_id}/suspend", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- SpendPolicy ----
    def create_spend_policy(self, payload, headers):
        return self._request("POST", "/spend-policies", payload, headers)

    def get_spend_policy(self, policy_id, headers):
        return self._request("GET", f"/spend-policies/{policy_id}", headers=headers)

    def list_spend_policies(self, headers, params=None):
        return self._request("GET", "/spend-policies", headers=headers, params=params)

    # ---- Employee ----
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    # ---- GlAccount ----
    def create_gl_account(self, payload, headers):
        return self._request("POST", "/gl-accounts", payload, headers)

    def get_gl_account(self, gl_account_id, headers):
        return self._request("GET", f"/gl-accounts/{gl_account_id}", headers=headers)

    def list_gl_accounts(self, headers, params=None):
        return self._request("GET", "/gl-accounts", headers=headers, params=params)

    # ---- Card ----
    def create_card(self, payload, headers):
        return self._request("POST", "/cards", payload, headers)

    def get_card(self, card_id, headers):
        return self._request("GET", f"/cards/{card_id}", headers=headers)

    def list_cards(self, headers, params=None):
        return self._request("GET", "/cards", headers=headers, params=params)

    def activate_card(self, card_id, headers):
        return self._request("POST", f"/cards/{card_id}/activate", {}, headers)

    def freeze_card(self, card_id, headers):
        return self._request("POST", f"/cards/{card_id}/freeze", {}, headers)

    def unfreeze_card(self, card_id, headers):
        return self._request("POST", f"/cards/{card_id}/unfreeze", {}, headers)

    def terminate_card(self, card_id, headers):
        return self._request("POST", f"/cards/{card_id}/terminate", {}, headers)

    # ---- Transaction ----
    def capture_transaction(self, card_id, payload, headers):
        return self._request("POST", f"/cards/{card_id}/transactions", payload, headers)

    def get_transaction(self, tx_id, headers):
        return self._request("GET", f"/transactions/{tx_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    def code_transaction(self, tx_id, payload, headers):
        return self._request("PATCH", f"/transactions/{tx_id}", payload, headers)

    def clear_transaction(self, tx_id, headers):
        return self._request("POST", f"/transactions/{tx_id}/clear", {}, headers)

    def settle_transaction(self, tx_id, payload, headers):
        return self._request("POST", f"/transactions/{tx_id}/settle", payload, headers)

    def reverse_transaction(self, tx_id, headers):
        return self._request("POST", f"/transactions/{tx_id}/reverse", {}, headers)

    def upload_receipt(self, tx_id, payload, headers):
        return self._request("POST", f"/transactions/{tx_id}/receipts", payload, headers)

    def list_transaction_receipts(self, tx_id, headers):
        return self._request("GET", f"/transactions/{tx_id}/receipts", headers=headers)

    def approve_review(self, tx_id, headers):
        return self._request("POST", f"/transactions/{tx_id}/approve-review", {}, headers)

    def flag_transaction(self, tx_id, payload, headers):
        return self._request("POST", f"/transactions/{tx_id}/flag", payload, headers)

    # ---- Receipt ----
    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"/receipts/{receipt_id}", headers=headers)

    def list_receipts(self, headers, params=None):
        return self._request("GET", "/receipts", headers=headers, params=params)

    # ---- ApprovalRequest ----
    def open_approval_request(self, tx_id, payload, headers):
        return self._request("POST", f"/transactions/{tx_id}/approval-requests", payload, headers)

    def get_approval_request(self, ar_id, headers):
        return self._request("GET", f"/approval-requests/{ar_id}", headers=headers)

    def list_approval_requests(self, headers, params=None):
        return self._request("GET", "/approval-requests", headers=headers, params=params)

    def approve_approval_request(self, ar_id, payload, headers):
        return self._request("POST", f"/approval-requests/{ar_id}/approve", payload, headers)

    def reject_approval_request(self, ar_id, payload, headers):
        return self._request("POST", f"/approval-requests/{ar_id}/reject", payload, headers)

    def resubmit_approval_request(self, ar_id, headers):
        return self._request("POST", f"/approval-requests/{ar_id}/resubmit", {}, headers)

    # ---- ReimbursementClaim ----
    def create_reimbursement_claim(self, payload, headers):
        return self._request("POST", "/reimbursement-claims", payload, headers)

    def get_reimbursement_claim(self, claim_id, headers):
        return self._request("GET", f"/reimbursement-claims/{claim_id}", headers=headers)

    def list_reimbursement_claims(self, headers, params=None):
        return self._request("GET", "/reimbursement-claims", headers=headers, params=params)

    def submit_reimbursement_claim(self, claim_id, headers):
        return self._request("POST", f"/reimbursement-claims/{claim_id}/submit", {}, headers)

    def approve_reimbursement_claim(self, claim_id, headers):
        return self._request("POST", f"/reimbursement-claims/{claim_id}/approve", {}, headers)

    def reject_reimbursement_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/reimbursement-claims/{claim_id}/reject", payload, headers)

    def revise_reimbursement_claim(self, claim_id, headers):
        return self._request("POST", f"/reimbursement-claims/{claim_id}/revise", {}, headers)

    def pay_reimbursement_claim(self, claim_id, headers):
        return self._request("POST", f"/reimbursement-claims/{claim_id}/pay", {}, headers)

    # ---- Statement ----
    def get_statement(self, stmt_id, headers):
        return self._request("GET", f"/statements/{stmt_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/statements", headers=headers, params=params)

    def close_statement(self, stmt_id, headers):
        return self._request("POST", f"/statements/{stmt_id}/close", {}, headers)

    def issue_statement(self, stmt_id, headers):
        return self._request("POST", f"/statements/{stmt_id}/issue", {}, headers)

    def cashback_summary(self, stmt_id, headers):
        return self._request("GET", f"/statements/{stmt_id}/cashback-summary", headers=headers)

    # ---- Repayment ----
    def create_repayment(self, payload, headers):
        return self._request("POST", "/repayments", payload, headers)

    def get_repayment(self, repayment_id, headers):
        return self._request("GET", f"/repayments/{repayment_id}", headers=headers)

    def list_repayments(self, headers, params=None):
        return self._request("GET", "/repayments", headers=headers, params=params)

    def clear_repayment(self, repayment_id, headers):
        return self._request("POST", f"/repayments/{repayment_id}/clear", {}, headers)

    def fail_repayment(self, repayment_id, headers):
        return self._request("POST", f"/repayments/{repayment_id}/fail", {}, headers)

    def reverse_repayment(self, repayment_id, headers):
        return self._request("POST", f"/repayments/{repayment_id}/reverse", {}, headers)

    # ---- RewardAccount ----
    def get_reward_account(self, reward_account_id, headers):
        return self._request("GET", f"/reward-accounts/{reward_account_id}", headers=headers)

    def list_reward_accounts(self, headers, params=None):
        return self._request("GET", "/reward-accounts", headers=headers, params=params)

    def redeem_reward(self, reward_account_id, payload, headers):
        return self._request("POST", f"/reward-accounts/{reward_account_id}/redeem", payload, headers)

    # ---- SpendAuthorization ----
    def create_spend_authorization(self, payload, headers):
        return self._request("POST", "/spend-authorizations", payload, headers)

    def get_spend_authorization(self, auth_id, headers):
        return self._request("GET", f"/spend-authorizations/{auth_id}", headers=headers)

    def list_spend_authorizations(self, headers, params=None):
        return self._request("GET", "/spend-authorizations", headers=headers, params=params)

    def consume_spend_authorization(self, auth_id, headers):
        return self._request("POST", f"/spend-authorizations/{auth_id}/consume", {}, headers)

    def cancel_spend_authorization(self, auth_id, headers):
        return self._request("POST", f"/spend-authorizations/{auth_id}/cancel", {}, headers)

    # ---- ErpSyncBatch ----
    def create_erp_sync_batch(self, payload, headers):
        return self._request("POST", "/erp-sync-batches", payload, headers)

    def get_erp_sync_batch(self, batch_id, headers):
        return self._request("GET", f"/erp-sync-batches/{batch_id}", headers=headers)

    def list_erp_sync_batches(self, headers, params=None):
        return self._request("GET", "/erp-sync-batches", headers=headers, params=params)

    def post_erp_sync_batch(self, batch_id, headers):
        return self._request("POST", f"/erp-sync-batches/{batch_id}/post", {}, headers)

    def discard_erp_sync_batch(self, batch_id, headers):
        return self._request("POST", f"/erp-sync-batches/{batch_id}/discard", {}, headers)


api_client = ApiClient()
