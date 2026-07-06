"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # --- Newspaper ---
    def create_newspaper(self, payload, headers):
        return self._request("POST", "/newspapers", payload, headers=headers)

    def get_newspaper(self, newspaper_id, headers):
        return self._request("GET", f"/newspapers/{newspaper_id}", headers=headers)

    # --- Account ---
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers=headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    # --- StatutoryRequirement ---
    def create_statutory_requirement(self, payload, headers):
        return self._request("POST", "/statutory-requirements", payload, headers=headers)

    def list_statutory_requirements(self, headers, params=None):
        return self._request("GET", "/statutory-requirements", headers=headers, params=params)

    # --- Notice ---
    def create_notice(self, payload, headers):
        return self._request("POST", "/notices", payload, headers=headers)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/notices/{notice_id}", headers=headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/notices", headers=headers, params=params)

    def submit_notice(self, notice_id, headers):
        return self._request("POST", f"/notices/{notice_id}/submit", None, headers=headers)

    def list_notice_proofs(self, notice_id, headers):
        return self._request("GET", f"/notices/{notice_id}/proofs", headers=headers)

    def schedule_notice(self, notice_id, payload, headers):
        return self._request("POST", f"/notices/{notice_id}/schedule", payload, headers=headers)

    def list_notice_insertions(self, notice_id, headers):
        return self._request("GET", f"/notices/{notice_id}/insertions", headers=headers)

    def add_insertion(self, notice_id, payload, headers):
        return self._request("POST", f"/notices/{notice_id}/insertions", payload, headers=headers)

    def list_notice_affidavits(self, notice_id, headers):
        return self._request("GET", f"/notices/{notice_id}/affidavits", headers=headers)

    def archive_notice(self, notice_id, headers):
        return self._request("POST", f"/notices/{notice_id}/archive", None, headers=headers)

    # --- Proof ---
    def approve_proof(self, proof_id, payload, headers):
        return self._request("POST", f"/proofs/{proof_id}/approve", payload, headers=headers)

    def reject_proof(self, proof_id, payload, headers):
        return self._request("POST", f"/proofs/{proof_id}/reject", payload, headers=headers)

    # --- Insertion ---
    def get_insertion(self, insertion_id, headers):
        return self._request("GET", f"/insertions/{insertion_id}", headers=headers)

    def list_insertions(self, headers, params=None):
        return self._request("GET", "/insertions", headers=headers, params=params)

    def publish_insertion(self, insertion_id, payload, headers):
        return self._request("POST", f"/insertions/{insertion_id}/publish", payload, headers=headers)

    def skip_insertion(self, insertion_id, headers):
        return self._request("POST", f"/insertions/{insertion_id}/skip", None, headers=headers)

    def cancel_insertion(self, insertion_id, headers):
        return self._request("POST", f"/insertions/{insertion_id}/cancel", None, headers=headers)

    # --- Affidavit ---
    def get_affidavit(self, affidavit_id, headers):
        return self._request("GET", f"/affidavits/{affidavit_id}", headers=headers)

    def issue_affidavit(self, affidavit_id, payload, headers):
        return self._request("POST", f"/affidavits/{affidavit_id}/issue", payload, headers=headers)

    def void_affidavit(self, affidavit_id, payload, headers):
        return self._request("POST", f"/affidavits/{affidavit_id}/void", payload, headers=headers)

    # --- Invoice ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    # --- InvoiceLineItem ---
    def get_invoice_line_item(self, line_item_id, headers):
        return self._request("GET", f"/invoice-line-items/{line_item_id}", headers=headers)

    def list_invoice_line_items(self, headers, params=None):
        return self._request("GET", "/invoice-line-items", headers=headers, params=params)

    # --- Payment ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers=headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)


api_client = ApiClient()
