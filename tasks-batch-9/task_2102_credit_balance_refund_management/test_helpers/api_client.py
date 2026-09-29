"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock and operations checkpoint ---------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_aging_sweep(self, headers, payload=None):
        return self._request("POST", "/ops/run-aging-sweep", payload or {}, headers)

    # --- Payers -------------------------------------------------------------
    def create_payer(self, payload, headers):
        return self._request("POST", "/payers", payload, headers)

    def list_payers(self, headers, params=None):
        return self._request("GET", "/payers", headers=headers, params=params)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/payers/{payer_id}", headers=headers)

    # --- Patient accounts ---------------------------------------------------
    def create_patient_account(self, payload, headers):
        return self._request("POST", "/patient-accounts", payload, headers)

    def list_patient_accounts(self, headers, params=None):
        return self._request("GET", "/patient-accounts", headers=headers, params=params)

    def get_patient_account(self, account_id, headers):
        return self._request("GET", f"/patient-accounts/{account_id}", headers=headers)

    def set_patient_account_status(self, account_id, payload, headers):
        return self._request(
            "POST", f"/patient-accounts/{account_id}/status", payload, headers
        )

    def post_account_transaction(self, account_id, payload, headers):
        return self._request(
            "POST", f"/patient-accounts/{account_id}/transactions", payload, headers
        )

    # --- Ledger -------------------------------------------------------------
    def list_account_transactions(self, headers, params=None):
        return self._request(
            "GET", "/account-transactions", headers=headers, params=params
        )

    def get_account_transaction(self, transaction_id, headers):
        return self._request(
            "GET", f"/account-transactions/{transaction_id}", headers=headers
        )

    def reverse_account_transaction(self, transaction_id, payload, headers):
        return self._request(
            "POST", f"/account-transactions/{transaction_id}/reverse", payload, headers
        )

    # --- Credit balances ----------------------------------------------------
    def run_identify_sweep(self, payload, headers):
        return self._request("POST", "/credit-balances/identify-sweep", payload, headers)

    def list_credit_balances(self, headers, params=None):
        return self._request("GET", "/credit-balances", headers=headers, params=params)

    def get_credit_balance(self, credit_balance_id, headers):
        return self._request(
            "GET", f"/credit-balances/{credit_balance_id}", headers=headers
        )

    def start_credit_balance_review(self, credit_balance_id, payload, headers):
        return self._request(
            "POST", f"/credit-balances/{credit_balance_id}/start-review", payload, headers
        )

    def attribute_credit_balance(self, credit_balance_id, payload, headers):
        return self._request(
            "POST", f"/credit-balances/{credit_balance_id}/attribute", payload, headers
        )

    def write_off_credit_balance(self, credit_balance_id, payload, headers):
        return self._request(
            "POST", f"/credit-balances/{credit_balance_id}/write-off", payload, headers
        )

    # --- Root-cause findings ------------------------------------------------
    def create_root_cause_finding(self, payload, headers):
        return self._request("POST", "/root-cause-findings", payload, headers)

    def list_root_cause_findings(self, headers, params=None):
        return self._request(
            "GET", "/root-cause-findings", headers=headers, params=params
        )

    def get_root_cause_finding(self, finding_id, headers):
        return self._request(
            "GET", f"/root-cause-findings/{finding_id}", headers=headers
        )

    # --- Refund requests ----------------------------------------------------
    def create_refund_request(self, payload, headers):
        return self._request("POST", "/refund-requests", payload, headers)

    def list_refund_requests(self, headers, params=None):
        return self._request("GET", "/refund-requests", headers=headers, params=params)

    def get_refund_request(self, refund_request_id, headers):
        return self._request(
            "GET", f"/refund-requests/{refund_request_id}", headers=headers
        )

    def submit_refund_request(self, refund_request_id, payload, headers):
        return self._request(
            "POST", f"/refund-requests/{refund_request_id}/submit", payload, headers
        )

    def decide_refund_request(self, refund_request_id, payload, headers):
        return self._request(
            "POST", f"/refund-requests/{refund_request_id}/decision", payload, headers
        )

    def cancel_refund_request(self, refund_request_id, payload, headers):
        return self._request(
            "POST", f"/refund-requests/{refund_request_id}/cancel", payload, headers
        )

    # --- Refund approvals ---------------------------------------------------
    def list_refund_approvals(self, headers, params=None):
        return self._request("GET", "/refund-approvals", headers=headers, params=params)

    def get_refund_approval(self, approval_id, headers):
        return self._request("GET", f"/refund-approvals/{approval_id}", headers=headers)

    # --- Check runs ---------------------------------------------------------
    def create_refund_batch(self, payload, headers):
        return self._request("POST", "/refund-batches", payload, headers)

    def list_refund_batches(self, headers, params=None):
        return self._request("GET", "/refund-batches", headers=headers, params=params)

    def get_refund_batch(self, batch_id, headers):
        return self._request("GET", f"/refund-batches/{batch_id}", headers=headers)

    def add_refund_batch_item(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/refund-batches/{batch_id}/items", payload, headers
        )

    def lock_refund_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/refund-batches/{batch_id}/lock", payload, headers
        )

    def unlock_refund_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/refund-batches/{batch_id}/unlock", payload or {}, headers
        )

    def issue_refund_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/refund-batches/{batch_id}/issue", payload, headers
        )

    # --- Checks -------------------------------------------------------------
    def list_check_disbursements(self, headers, params=None):
        return self._request(
            "GET", "/check-disbursements", headers=headers, params=params
        )

    def get_check_disbursement(self, check_id, headers):
        return self._request("GET", f"/check-disbursements/{check_id}", headers=headers)

    def clear_check(self, check_id, payload, headers):
        return self._request(
            "POST", f"/check-disbursements/{check_id}/clear", payload or {}, headers
        )

    def void_check(self, check_id, payload, headers):
        return self._request(
            "POST", f"/check-disbursements/{check_id}/void", payload, headers
        )

    def reissue_check(self, check_id, payload, headers):
        return self._request(
            "POST", f"/check-disbursements/{check_id}/reissue", payload, headers
        )

    # --- Take-back notices --------------------------------------------------
    def create_take_back_notice(self, payload, headers):
        return self._request("POST", "/take-back-notices", payload, headers)

    def list_take_back_notices(self, headers, params=None):
        return self._request(
            "GET", "/take-back-notices", headers=headers, params=params
        )

    def get_take_back_notice(self, notice_id, headers):
        return self._request("GET", f"/take-back-notices/{notice_id}", headers=headers)

    def apply_offsets(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/take-back-notices/{notice_id}/offset-applications",
            payload, headers,
        )

    def dispute_take_back_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/take-back-notices/{notice_id}/dispute", payload, headers
        )

    def withdraw_take_back_dispute(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/take-back-notices/{notice_id}/withdraw-dispute",
            payload or {}, headers,
        )

    # --- Offset applications ------------------------------------------------
    def list_offset_applications(self, headers, params=None):
        return self._request(
            "GET", "/offset-applications", headers=headers, params=params
        )

    def get_offset_application(self, offset_application_id, headers):
        return self._request(
            "GET", f"/offset-applications/{offset_application_id}", headers=headers
        )

    def reverse_offset_application(self, offset_application_id, payload, headers):
        return self._request(
            "POST", f"/offset-applications/{offset_application_id}/reverse",
            payload or {}, headers,
        )

    # --- Medicare obligations -----------------------------------------------
    def list_medicare_obligations(self, headers, params=None):
        return self._request(
            "GET", "/medicare-obligations", headers=headers, params=params
        )

    def get_medicare_obligation(self, obligation_id, headers):
        return self._request(
            "GET", f"/medicare-obligations/{obligation_id}", headers=headers
        )

    def report_medicare_obligation(self, obligation_id, payload, headers):
        return self._request(
            "POST", f"/medicare-obligations/{obligation_id}/report", payload, headers
        )

    # --- Unclaimed property -------------------------------------------------
    def create_escheatment_record(self, payload, headers):
        return self._request("POST", "/escheatment-records", payload, headers)

    def list_escheatment_records(self, headers, params=None):
        return self._request(
            "GET", "/escheatment-records", headers=headers, params=params
        )

    def get_escheatment_record(self, escheatment_record_id, headers):
        return self._request(
            "GET", f"/escheatment-records/{escheatment_record_id}", headers=headers
        )

    def record_due_diligence(self, escheatment_record_id, payload, headers):
        return self._request(
            "POST", f"/escheatment-records/{escheatment_record_id}/due-diligence",
            payload, headers,
        )

    def remit_escheatment_record(self, escheatment_record_id, payload, headers):
        return self._request(
            "POST", f"/escheatment-records/{escheatment_record_id}/remit",
            payload or {}, headers,
        )

    # --- Compliance reports -------------------------------------------------
    def create_compliance_report(self, payload, headers):
        return self._request("POST", "/compliance-reports", payload, headers)

    def list_compliance_reports(self, headers, params=None):
        return self._request(
            "GET", "/compliance-reports", headers=headers, params=params
        )

    def get_compliance_report(self, report_id, headers):
        return self._request("GET", f"/compliance-reports/{report_id}", headers=headers)

    def finalize_compliance_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/compliance-reports/{report_id}/finalize", payload or {}, headers
        )


api_client = ApiClient()
