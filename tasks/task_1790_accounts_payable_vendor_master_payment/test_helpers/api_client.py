"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving / ops ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_vendor_sweep(self, headers):
        return self._request("POST", "/vendor-sweeps/run", {}, headers)

    # --- vendors ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def patch_vendor(self, vendor_id, payload, headers):
        return self._request("PATCH", f"/vendors/{vendor_id}", payload, headers)

    def submit_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/submit", {}, headers)

    def approve_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/approve", {}, headers)

    def reject_vendor(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendors/{vendor_id}/reject", payload, headers)

    def suspend_vendor(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendors/{vendor_id}/suspend", payload, headers)

    def reinstate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/reinstate", {}, headers)

    def reactivate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/reactivate", {}, headers)

    def deactivate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/deactivate", {}, headers)

    def merge_vendor(self, survivor_id, payload, headers):
        return self._request("POST", f"/vendors/{survivor_id}/merge", payload, headers)

    def list_merge_records(self, headers, params=None):
        return self._request("GET", "/vendor-merge-records", headers=headers, params=params)

    def get_merge_record(self, record_id, headers):
        return self._request("GET", f"/vendor-merge-records/{record_id}", headers=headers)

    # --- bank accounts & callbacks ---
    def create_bank_account(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendors/{vendor_id}/bank-accounts", payload, headers)

    def list_bank_accounts(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vendors/{vendor_id}/bank-accounts", headers=headers, params=params)

    def get_bank_account(self, account_id, headers):
        return self._request("GET", f"/bank-accounts/{account_id}", headers=headers)

    def confirm_bank_verification(self, account_id, payload, headers):
        return self._request("POST", f"/bank-accounts/{account_id}/confirm-verification", payload, headers)

    def disable_bank_account(self, account_id, headers):
        return self._request("POST", f"/bank-accounts/{account_id}/disable", {}, headers)

    def list_callback_verifications(self, account_id, headers, params=None):
        return self._request("GET", f"/bank-accounts/{account_id}/callback-verifications", headers=headers, params=params)

    # --- documents ---
    def create_document(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendors/{vendor_id}/documents", payload, headers)

    def list_documents(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vendors/{vendor_id}/documents", headers=headers, params=params)

    def supersede_document(self, document_id, headers):
        return self._request("POST", f"/documents/{document_id}/supersede", {}, headers)

    # --- watchlist & screening ---
    def create_watchlist_entry(self, payload, headers):
        return self._request("POST", "/watchlist-entries", payload, headers)

    def retire_watchlist_entry(self, entry_id, headers):
        return self._request("POST", f"/watchlist-entries/{entry_id}/retire", {}, headers)

    def list_screening_checks(self, headers, params=None):
        return self._request("GET", "/screening-checks", headers=headers, params=params)

    def get_screening_check(self, check_id, headers):
        return self._request("GET", f"/screening-checks/{check_id}", headers=headers)

    def list_sanctions_cases(self, headers, params=None):
        return self._request("GET", "/sanctions-cases", headers=headers, params=params)

    def get_sanctions_case(self, case_id, headers):
        return self._request("GET", f"/sanctions-cases/{case_id}", headers=headers)

    def disposition_sanctions_case(self, case_id, payload, headers):
        return self._request("POST", f"/sanctions-cases/{case_id}/disposition", payload, headers)

    # --- approval matrix ---
    def create_matrix_rule(self, payload, headers):
        return self._request("POST", "/approval-matrix-rules", payload, headers)

    def retire_matrix_rule(self, rule_id, headers):
        return self._request("POST", f"/approval-matrix-rules/{rule_id}/retire", {}, headers)

    # --- invoices ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def patch_invoice(self, invoice_id, payload, headers):
        return self._request("PATCH", f"/invoices/{invoice_id}", payload, headers)

    def submit_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/submit", {}, headers)

    def approve_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/approve", payload, headers)

    def reject_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/reject", payload, headers)

    def resubmit_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/resubmit", {}, headers)

    def cancel_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/cancel", payload, headers)

    def list_invoice_approvals(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/approvals", headers=headers, params=params)

    # --- payment runs & payments ---
    def create_payment_run(self, payload, headers):
        return self._request("POST", "/payment-runs", payload, headers)

    def get_payment_run(self, run_id, headers):
        return self._request("GET", f"/payment-runs/{run_id}", headers=headers)

    def add_invoice_to_run(self, run_id, payload, headers):
        return self._request("POST", f"/payment-runs/{run_id}/invoices", payload, headers)

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/void", {}, headers)

    def compile_payment_run(self, run_id, headers):
        return self._request("POST", f"/payment-runs/{run_id}/compile", {}, headers)

    def uncompile_payment_run(self, run_id, headers):
        return self._request("POST", f"/payment-runs/{run_id}/uncompile", {}, headers)

    def approve_payment_run(self, run_id, headers):
        return self._request("POST", f"/payment-runs/{run_id}/approve", {}, headers)

    def revoke_payment_run_approval(self, run_id, headers):
        return self._request("POST", f"/payment-runs/{run_id}/revoke-approval", {}, headers)

    def release_payment_run(self, run_id, headers):
        return self._request("POST", f"/payment-runs/{run_id}/release", {}, headers)

    def submit_positive_pay_acks(self, run_id, payload, headers):
        return self._request("POST", f"/payment-runs/{run_id}/positive-pay-acks", payload, headers)

    def void_payment_run(self, run_id, headers):
        return self._request("POST", f"/payment-runs/{run_id}/void", {}, headers)

    def list_run_payments(self, run_id, headers, params=None):
        return self._request("GET", f"/payment-runs/{run_id}/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # --- audit ---
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)


api_client = ApiClient()
