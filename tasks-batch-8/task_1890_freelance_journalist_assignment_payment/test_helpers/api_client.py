"""API client: one method per endpoint defined in the PRD (section 4).

All paths live under the /freelance-desk prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/freelance-desk"


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD section 2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             payload, headers)

    # --- DeskConfig (PRD section 3.10) ---
    def bootstrap_desk_config(self, payload, headers):
        return self._request("POST", f"{PREFIX}/desk-config", payload, headers)

    def get_desk_config(self, headers):
        return self._request("GET", f"{PREFIX}/desk-config", headers=headers)

    # --- Contributors (PRD section 3.1) ---
    def create_contributor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contributors", payload, headers)

    def list_contributors(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/contributors",
                             headers=headers, params=params)

    def get_contributor(self, contributor_id, headers):
        return self._request("GET", f"{PREFIX}/contributors/{contributor_id}",
                             headers=headers)

    def suspend_contributor(self, contributor_id, headers):
        return self._request("POST",
                             f"{PREFIX}/contributors/{contributor_id}/suspend",
                             headers=headers)

    def reinstate_contributor(self, contributor_id, headers):
        return self._request("POST",
                             f"{PREFIX}/contributors/{contributor_id}/reinstate",
                             headers=headers)

    def terminate_contributor(self, contributor_id, headers):
        return self._request("POST",
                             f"{PREFIX}/contributors/{contributor_id}/terminate",
                             headers=headers)

    # --- Rate agreements (PRD section 3.2) ---
    def create_rate_agreement(self, contributor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contributors/{contributor_id}/rate-agreements",
            payload, headers)

    def list_rate_agreements(self, contributor_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/contributors/{contributor_id}/rate-agreements",
            headers=headers, params=params)

    def get_rate_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/rate-agreements/{agreement_id}",
                             headers=headers)

    def revoke_rate_agreement(self, agreement_id, headers):
        return self._request("POST",
                             f"{PREFIX}/rate-agreements/{agreement_id}/revoke",
                             headers=headers)

    # --- Assignments (PRD sections 3.3-3.4) ---
    def create_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/assignments",
                             headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"{PREFIX}/assignments/{assignment_id}",
                             headers=headers)

    def offer_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"{PREFIX}/assignments/{assignment_id}/offer",
                             headers=headers)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"{PREFIX}/assignments/{assignment_id}/accept",
                             headers=headers)

    def start_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"{PREFIX}/assignments/{assignment_id}/start",
                             headers=headers)

    def submit_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"{PREFIX}/assignments/{assignment_id}/submit",
                             headers=headers)

    def kill_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"{PREFIX}/assignments/{assignment_id}/kill",
                             headers=headers)

    def accept_for_publication(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/assignments/{assignment_id}/accept-for-publication",
            payload, headers)

    # --- Verification reports (PRD section 3.5) ---
    def list_verification_reports(self, assignment_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/assignments/{assignment_id}/verification-reports",
            headers=headers, params=params)

    def get_verification_report(self, report_id, headers):
        return self._request("GET",
                             f"{PREFIX}/verification-reports/{report_id}",
                             headers=headers)

    def record_verification_result(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/verification-reports/{report_id}/record-result",
            payload, headers)

    def adjudicate_verification_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/verification-reports/{report_id}/adjudicate",
            payload, headers)

    # --- Expense claims (PRD section 3.7) ---
    def create_expense_claim(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/assignments/{assignment_id}/expense-claims",
            payload, headers)

    def list_expense_claims(self, assignment_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/assignments/{assignment_id}/expense-claims",
            headers=headers, params=params)

    def get_expense_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/expense-claims/{claim_id}",
                             headers=headers)

    def decide_expense_claim(self, claim_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/expense-claims/{claim_id}/decide",
                             payload, headers)

    def submit_expense_claim(self, claim_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/expense-claims/{claim_id}/submit",
                             payload, headers)

    def settle_expense_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/expense-claims/{claim_id}/settle-decision",
            payload, headers)

    # --- Rights purchases (PRD section 3.6) ---
    def list_rights_purchases(self, assignment_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/assignments/{assignment_id}/rights-purchases",
            headers=headers, params=params)

    def get_rights_purchase(self, purchase_id, headers):
        return self._request("GET", f"{PREFIX}/rights-purchases/{purchase_id}",
                             headers=headers)

    def record_reuse(self, purchase_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rights-purchases/{purchase_id}/record-reuse",
            headers=headers)

    # --- Tax documents (PRD section 3.8) ---
    def create_tax_document(self, contributor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contributors/{contributor_id}/tax-documents",
            payload, headers)

    def list_tax_documents(self, contributor_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/contributors/{contributor_id}/tax-documents",
            headers=headers, params=params)

    def get_tax_document(self, document_id, headers):
        return self._request("GET", f"{PREFIX}/tax-documents/{document_id}",
                             headers=headers)

    def verify_tax_document(self, document_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/tax-documents/{document_id}/verify",
                             payload, headers)

    # --- Invoices (PRD section 3.8) ---
    def create_invoice(self, assignment_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/assignments/{assignment_id}/invoices",
                             payload, headers)

    def list_assignment_invoices(self, assignment_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/assignments/{assignment_id}/invoices",
            headers=headers, params=params)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices",
                             headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}",
                             headers=headers)

    def verify_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/verify",
                             payload, headers)

    def approve_invoice(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/approve",
                             headers=headers)

    # --- Payment batches (PRD section 3.9) ---
    def create_payment_batch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payment-batches",
                             payload, headers)

    def list_payment_batches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/payment-batches",
                             headers=headers, params=params)

    def get_payment_batch(self, batch_id, headers):
        return self._request("GET", f"{PREFIX}/payment-batches/{batch_id}",
                             headers=headers)

    def add_invoice_to_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/payment-batches/{batch_id}/add-invoice",
            payload, headers)

    def lock_batch(self, batch_id, headers):
        return self._request("POST",
                             f"{PREFIX}/payment-batches/{batch_id}/lock",
                             headers=headers)

    def release_batch(self, batch_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/payment-batches/{batch_id}/release",
                             payload, headers)

    def cancel_batch(self, batch_id, headers):
        return self._request("POST",
                             f"{PREFIX}/payment-batches/{batch_id}/cancel",
                             headers=headers)

    # --- Ledger (PRD section 3.9) ---
    def list_contributor_ledger_entries(self, contributor_id, headers,
                                        params=None):
        return self._request(
            "GET", f"{PREFIX}/contributors/{contributor_id}/ledger-entries",
            headers=headers, params=params)

    def list_invoice_ledger_entries(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/invoices/{invoice_id}/ledger-entries",
            headers=headers, params=params)


api_client = ApiClient()
