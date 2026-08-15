"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock/current_utc", headers=headers)

    # ------------------------------------------------------------------
    # Loans
    # ------------------------------------------------------------------
    def create_loan(self, payload, headers):
        return self._request("POST", "/servicing/loans", payload, headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/servicing/loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/servicing/loans/{loan_id}", headers=headers)

    def activate_loan(self, loan_id, headers):
        return self._request("POST", f"/servicing/loans/{loan_id}/activate", {}, headers)

    def payoff_loan(self, loan_id, headers):
        return self._request("POST", f"/servicing/loans/{loan_id}/payoff", {}, headers)

    def transfer_out_loan(self, loan_id, headers):
        return self._request("POST", f"/servicing/loans/{loan_id}/transfer-out", {}, headers)

    # ------------------------------------------------------------------
    # Escrow accounts
    # ------------------------------------------------------------------
    def create_escrow_account(self, loan_id, payload, headers):
        return self._request("POST", f"/servicing/loans/{loan_id}/escrow-account",
                             payload, headers)

    def list_escrow_accounts(self, headers, params=None):
        return self._request("GET", "/servicing/escrow-accounts", headers=headers,
                             params=params)

    def get_escrow_account(self, account_id, headers):
        return self._request("GET", f"/servicing/escrow-accounts/{account_id}",
                             headers=headers)

    def activate_escrow_account(self, account_id, headers):
        return self._request("POST", f"/servicing/escrow-accounts/{account_id}/activate",
                             {}, headers)

    def suspend_escrow_account(self, account_id, headers):
        return self._request("POST", f"/servicing/escrow-accounts/{account_id}/suspend",
                             {}, headers)

    def reinstate_escrow_account(self, account_id, headers):
        return self._request("POST", f"/servicing/escrow-accounts/{account_id}/reinstate",
                             {}, headers)

    def hold_escrow_account(self, account_id, headers):
        return self._request("POST", f"/servicing/escrow-accounts/{account_id}/hold",
                             {}, headers)

    def release_hold_escrow_account(self, account_id, headers):
        return self._request("POST",
                             f"/servicing/escrow-accounts/{account_id}/release-hold",
                             {}, headers)

    def create_deposit(self, account_id, payload, headers):
        return self._request("POST", f"/servicing/escrow-accounts/{account_id}/deposits",
                             payload, headers)

    def list_ledger(self, account_id, headers, params=None):
        return self._request("GET", f"/servicing/escrow-accounts/{account_id}/ledger",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Escrow line items
    # ------------------------------------------------------------------
    def create_line_item(self, account_id, payload, headers):
        return self._request("POST",
                             f"/servicing/escrow-accounts/{account_id}/line-items",
                             payload, headers)

    def list_line_items(self, account_id, headers, params=None):
        return self._request("GET",
                             f"/servicing/escrow-accounts/{account_id}/line-items",
                             headers=headers, params=params)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/servicing/escrow-line-items/{line_item_id}",
                             headers=headers)

    def patch_line_item(self, line_item_id, payload, headers):
        return self._request("PATCH", f"/servicing/escrow-line-items/{line_item_id}",
                             payload, headers)

    def remove_line_item(self, line_item_id, headers):
        return self._request("POST",
                             f"/servicing/escrow-line-items/{line_item_id}/remove",
                             {}, headers)

    # ------------------------------------------------------------------
    # Payees
    # ------------------------------------------------------------------
    def create_payee(self, payload, headers):
        return self._request("POST", "/servicing/payees", payload, headers)

    def list_payees(self, headers, params=None):
        return self._request("GET", "/servicing/payees", headers=headers, params=params)

    def get_payee(self, payee_id, headers):
        return self._request("GET", f"/servicing/payees/{payee_id}", headers=headers)

    def verify_payee(self, payee_id, headers):
        return self._request("POST", f"/servicing/payees/{payee_id}/verify", {}, headers)

    def reject_payee(self, payee_id, headers):
        return self._request("POST", f"/servicing/payees/{payee_id}/reject", {}, headers)

    def suspend_payee(self, payee_id, headers):
        return self._request("POST", f"/servicing/payees/{payee_id}/suspend", {}, headers)

    def list_payee_disbursements(self, payee_id, headers, params=None):
        return self._request("GET", f"/servicing/payees/{payee_id}/disbursements",
                             headers=headers, params=params)

    def list_payee_line_items(self, payee_id, headers, params=None):
        return self._request("GET", f"/servicing/payees/{payee_id}/line-items",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Disbursements
    # ------------------------------------------------------------------
    def create_disbursement(self, account_id, payload, headers):
        return self._request("POST",
                             f"/servicing/escrow-accounts/{account_id}/disbursements",
                             payload, headers)

    def list_disbursements(self, account_id, headers, params=None):
        return self._request("GET",
                             f"/servicing/escrow-accounts/{account_id}/disbursements",
                             headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/servicing/disbursements/{disbursement_id}",
                             headers=headers)

    def patch_disbursement(self, disbursement_id, payload, headers):
        return self._request("PATCH", f"/servicing/disbursements/{disbursement_id}",
                             payload, headers)

    def release_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/servicing/disbursements/{disbursement_id}/release",
                             {}, headers)

    def cancel_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/servicing/disbursements/{disbursement_id}/cancel",
                             {}, headers)

    def mark_cleared_disbursement(self, disbursement_id, headers):
        return self._request("POST",
                             f"/servicing/disbursements/{disbursement_id}/mark-cleared",
                             {}, headers)

    def mark_returned_disbursement(self, disbursement_id, headers):
        return self._request("POST",
                             f"/servicing/disbursements/{disbursement_id}/mark-returned",
                             {}, headers)

    def list_disbursement_tax_records(self, disbursement_id, headers, params=None):
        return self._request("GET",
                             f"/servicing/disbursements/{disbursement_id}/tax-monitoring-records",
                             headers=headers, params=params)

    def list_disbursement_advances(self, disbursement_id, headers, params=None):
        return self._request("GET",
                             f"/servicing/disbursements/{disbursement_id}/advances",
                             headers=headers, params=params)

    def list_line_item_disbursements(self, line_item_id, headers, params=None):
        return self._request("GET",
                             f"/servicing/escrow-line-items/{line_item_id}/disbursements",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Insurance policies
    # ------------------------------------------------------------------
    def create_insurance_policy(self, loan_id, payload, headers):
        return self._request("POST", f"/servicing/loans/{loan_id}/insurance-policies",
                             payload, headers)

    def list_insurance_policies(self, loan_id, headers, params=None):
        return self._request("GET", f"/servicing/loans/{loan_id}/insurance-policies",
                             headers=headers, params=params)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/servicing/insurance-policies/{policy_id}",
                             headers=headers)

    def report_lapse(self, policy_id, headers):
        return self._request("POST",
                             f"/servicing/insurance-policies/{policy_id}/report-lapse",
                             {}, headers)

    def send_first_notice(self, policy_id, headers):
        return self._request("POST",
                             f"/servicing/insurance-policies/{policy_id}/send-first-notice",
                             {}, headers)

    def send_reminder_notice(self, policy_id, headers):
        return self._request("POST",
                             f"/servicing/insurance-policies/{policy_id}/send-reminder-notice",
                             {}, headers)

    def charge_force_placement(self, policy_id, payload, headers):
        return self._request("POST",
                             f"/servicing/insurance-policies/{policy_id}/charge-force-placement",
                             payload, headers)

    def reinstate_policy(self, policy_id, payload, headers):
        return self._request("POST",
                             f"/servicing/insurance-policies/{policy_id}/reinstate",
                             payload, headers)

    def refund_force_placement(self, policy_id, headers):
        return self._request("POST",
                             f"/servicing/insurance-policies/{policy_id}/refund-force-placement",
                             {}, headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST",
                             f"/servicing/insurance-policies/{policy_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Tax monitoring records
    # ------------------------------------------------------------------
    def create_tax_record(self, loan_id, payload, headers):
        return self._request("POST",
                             f"/servicing/loans/{loan_id}/tax-monitoring-records",
                             payload, headers)

    def list_tax_records(self, loan_id, headers, params=None):
        return self._request("GET",
                             f"/servicing/loans/{loan_id}/tax-monitoring-records",
                             headers=headers, params=params)

    def get_tax_record(self, record_id, headers):
        return self._request("GET", f"/servicing/tax-monitoring-records/{record_id}",
                             headers=headers)

    def mark_tax_paid(self, record_id, payload, headers):
        return self._request("POST",
                             f"/servicing/tax-monitoring-records/{record_id}/mark-paid",
                             payload, headers)

    # ------------------------------------------------------------------
    # Escrow analysis cycles
    # ------------------------------------------------------------------
    def create_analysis(self, account_id, payload, headers):
        return self._request("POST",
                             f"/servicing/escrow-accounts/{account_id}/analyses",
                             payload, headers)

    def list_analyses(self, account_id, headers, params=None):
        return self._request("GET",
                             f"/servicing/escrow-accounts/{account_id}/analyses",
                             headers=headers, params=params)

    def get_analysis(self, analysis_id, headers):
        return self._request("GET", f"/servicing/analyses/{analysis_id}", headers=headers)

    def compute_analysis(self, analysis_id, headers):
        return self._request("POST", f"/servicing/analyses/{analysis_id}/compute",
                             {}, headers)

    def issue_statement(self, analysis_id, headers):
        return self._request("POST",
                             f"/servicing/analyses/{analysis_id}/issue-statement",
                             {}, headers)

    def finalize_analysis(self, analysis_id, headers):
        return self._request("POST", f"/servicing/analyses/{analysis_id}/finalize",
                             {}, headers)

    def reopen_analysis(self, analysis_id, headers):
        return self._request("POST", f"/servicing/analyses/{analysis_id}/reopen",
                             {}, headers)

    def void_analysis(self, analysis_id, headers):
        return self._request("POST", f"/servicing/analyses/{analysis_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Payment change notices
    # ------------------------------------------------------------------
    def list_notices(self, analysis_id, headers, params=None):
        return self._request("GET", f"/servicing/analyses/{analysis_id}/notices",
                             headers=headers, params=params)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/servicing/notices/{notice_id}", headers=headers)

    def send_notice(self, notice_id, headers):
        return self._request("POST", f"/servicing/notices/{notice_id}/send", {}, headers)

    def acknowledge_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/servicing/notices/{notice_id}/acknowledge",
                             payload, headers)

    def apply_notice(self, notice_id, headers):
        return self._request("POST", f"/servicing/notices/{notice_id}/apply", {}, headers)

    def void_notice(self, notice_id, headers):
        return self._request("POST", f"/servicing/notices/{notice_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Escrow advances
    # ------------------------------------------------------------------
    def create_advance(self, account_id, payload, headers):
        return self._request("POST",
                             f"/servicing/escrow-accounts/{account_id}/advances",
                             payload, headers)

    def list_advances(self, account_id, headers, params=None):
        return self._request("GET",
                             f"/servicing/escrow-accounts/{account_id}/advances",
                             headers=headers, params=params)

    def get_advance(self, advance_id, headers):
        return self._request("GET", f"/servicing/advances/{advance_id}", headers=headers)

    def recover_advance(self, advance_id, payload, headers):
        return self._request("POST", f"/servicing/advances/{advance_id}/recover",
                             payload, headers)

    def write_off_advance(self, advance_id, headers):
        return self._request("POST", f"/servicing/advances/{advance_id}/write-off",
                             {}, headers)

    # ------------------------------------------------------------------
    # Error resolution cases
    # ------------------------------------------------------------------
    def create_error_case(self, loan_id, payload, headers):
        return self._request("POST", f"/servicing/loans/{loan_id}/error-cases",
                             payload, headers)

    def list_error_cases(self, loan_id, headers, params=None):
        return self._request("GET", f"/servicing/loans/{loan_id}/error-cases",
                             headers=headers, params=params)

    def get_error_case(self, case_id, headers):
        return self._request("GET", f"/servicing/error-cases/{case_id}", headers=headers)

    def acknowledge_case(self, case_id, headers):
        return self._request("POST", f"/servicing/error-cases/{case_id}/acknowledge",
                             {}, headers)

    def assign_case(self, case_id, payload, headers):
        return self._request("POST", f"/servicing/error-cases/{case_id}/assign",
                             payload, headers)

    def extend_case(self, case_id, headers):
        return self._request("POST", f"/servicing/error-cases/{case_id}/extend",
                             {}, headers)

    def resolve_case(self, case_id, payload, headers):
        return self._request("POST", f"/servicing/error-cases/{case_id}/resolve",
                             payload, headers)

    def dismiss_case(self, case_id, payload, headers):
        return self._request("POST", f"/servicing/error-cases/{case_id}/dismiss",
                             payload, headers)


api_client = ApiClient()
