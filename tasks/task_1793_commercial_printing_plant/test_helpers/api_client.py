"""API client: one method per endpoint defined in the PRD §4 endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    # ---- Estimates ----
    def create_estimate(self, payload, headers):
        return self._request("POST", "/estimates", payload, headers)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/estimates/{estimate_id}", headers=headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/estimates", headers=headers, params=params)

    def revise_estimate(self, estimate_id, payload, headers):
        return self._request("PUT", f"/estimates/{estimate_id}", payload, headers)

    def quote_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/quote", {}, headers)

    def accept_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/accept", {}, headers)

    def decline_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/decline", {}, headers)

    # ---- Jobs ----
    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/jobs", headers=headers, params=params)

    def record_delivery(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/record-delivery", payload, headers)

    def cancel_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/cancel", payload, headers)

    # ---- Proofs ----
    def create_proof(self, payload, headers):
        return self._request("POST", "/proofs", payload, headers)

    def get_proof(self, proof_id, headers):
        return self._request("GET", f"/proofs/{proof_id}", headers=headers)

    def list_proofs(self, headers, params=None):
        return self._request("GET", "/proofs", headers=headers, params=params)

    def approve_proof(self, proof_id, headers):
        return self._request("POST", f"/proofs/{proof_id}/approve", {}, headers)

    def request_proof_changes(self, proof_id, payload, headers):
        return self._request("POST", f"/proofs/{proof_id}/request-changes", payload, headers)

    # ---- Paper stocks ----
    def create_paper_stock(self, payload, headers):
        return self._request("POST", "/paper-stocks", payload, headers)

    def get_paper_stock(self, stock_id, headers):
        return self._request("GET", f"/paper-stocks/{stock_id}", headers=headers)

    def list_paper_stocks(self, headers, params=None):
        return self._request("GET", "/paper-stocks", headers=headers, params=params)

    # ---- Paper purchase orders ----
    def create_paper_purchase_order(self, payload, headers):
        return self._request("POST", "/paper-purchase-orders", payload, headers)

    def get_paper_purchase_order(self, po_id, headers):
        return self._request("GET", f"/paper-purchase-orders/{po_id}", headers=headers)

    def list_paper_purchase_orders(self, headers, params=None):
        return self._request("GET", "/paper-purchase-orders", headers=headers, params=params)

    def receive_paper_purchase_order(self, po_id, payload, headers):
        return self._request("POST", f"/paper-purchase-orders/{po_id}/receive", payload, headers)

    def cancel_paper_purchase_order(self, po_id, headers):
        return self._request("POST", f"/paper-purchase-orders/{po_id}/cancel", {}, headers)

    # ---- Paper lots ----
    def get_paper_lot(self, lot_id, headers):
        return self._request("GET", f"/paper-lots/{lot_id}", headers=headers)

    def list_paper_lots(self, headers, params=None):
        return self._request("GET", "/paper-lots", headers=headers, params=params)

    # ---- Presses ----
    def create_press(self, payload, headers):
        return self._request("POST", "/presses", payload, headers)

    def get_press(self, press_id, headers):
        return self._request("GET", f"/presses/{press_id}", headers=headers)

    def list_presses(self, headers, params=None):
        return self._request("GET", "/presses", headers=headers, params=params)

    # ---- Press runs ----
    def create_press_run(self, payload, headers):
        return self._request("POST", "/press-runs", payload, headers)

    def get_press_run(self, run_id, headers):
        return self._request("GET", f"/press-runs/{run_id}", headers=headers)

    def list_press_runs(self, headers, params=None):
        return self._request("GET", "/press-runs", headers=headers, params=params)

    def complete_press_run(self, run_id, payload, headers):
        return self._request("POST", f"/press-runs/{run_id}/complete", payload, headers)

    def cancel_press_run(self, run_id, headers):
        return self._request("POST", f"/press-runs/{run_id}/cancel", {}, headers)

    # ---- Gang runs ----
    def create_gang_run(self, payload, headers):
        return self._request("POST", "/gang-runs", payload, headers)

    def get_gang_run(self, gang_id, headers):
        return self._request("GET", f"/gang-runs/{gang_id}", headers=headers)

    def list_gang_runs(self, headers, params=None):
        return self._request("GET", "/gang-runs", headers=headers, params=params)

    def add_gang_member(self, gang_id, payload, headers):
        return self._request("POST", f"/gang-runs/{gang_id}/members", payload, headers)

    def remove_gang_member(self, gang_id, payload, headers):
        return self._request("POST", f"/gang-runs/{gang_id}/remove-member", payload, headers)

    def lock_gang_run(self, gang_id, headers):
        return self._request("POST", f"/gang-runs/{gang_id}/lock", {}, headers)

    def unlock_gang_run(self, gang_id, headers):
        return self._request("POST", f"/gang-runs/{gang_id}/unlock", {}, headers)

    # ---- Bindery tickets ----
    def create_bindery_ticket(self, payload, headers):
        return self._request("POST", "/bindery-tickets", payload, headers)

    def get_bindery_ticket(self, ticket_id, headers):
        return self._request("GET", f"/bindery-tickets/{ticket_id}", headers=headers)

    def list_bindery_tickets(self, headers, params=None):
        return self._request("GET", "/bindery-tickets", headers=headers, params=params)

    def complete_bindery_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/bindery-tickets/{ticket_id}/complete", payload, headers)

    # ---- Mail drops ----
    def create_mail_drop(self, payload, headers):
        return self._request("POST", "/mail-drops", payload, headers)

    def get_mail_drop(self, drop_id, headers):
        return self._request("GET", f"/mail-drops/{drop_id}", headers=headers)

    def list_mail_drops(self, headers, params=None):
        return self._request("GET", "/mail-drops", headers=headers, params=params)

    def presort_mail_drop(self, drop_id, headers):
        return self._request("POST", f"/mail-drops/{drop_id}/presort", {}, headers)

    def drop_mail_drop(self, drop_id, headers):
        return self._request("POST", f"/mail-drops/{drop_id}/drop", {}, headers)

    # ---- Invoices ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)

    def apply_credit(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/apply-credit", payload, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute", payload, headers)

    # ---- Reprint claims ----
    def create_reprint_claim(self, payload, headers):
        return self._request("POST", "/reprint-claims", payload, headers)

    def get_reprint_claim(self, claim_id, headers):
        return self._request("GET", f"/reprint-claims/{claim_id}", headers=headers)

    def list_reprint_claims(self, headers, params=None):
        return self._request("GET", "/reprint-claims", headers=headers, params=params)

    def review_reprint_claim(self, claim_id, headers):
        return self._request("POST", f"/reprint-claims/{claim_id}/review", {}, headers)

    def approve_reprint_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/reprint-claims/{claim_id}/approve", payload, headers)

    def deny_reprint_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/reprint-claims/{claim_id}/deny", payload, headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
