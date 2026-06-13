"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── ServiceCategory ──────────────────────────────────────
    def create_service_category(self, payload, headers):
        return self._request("POST", "/service-categories", payload, headers)

    def get_service_category(self, category_id, headers):
        return self._request("GET", f"/service-categories/{category_id}", headers=headers)

    def list_service_categories(self, headers, params=None):
        return self._request("GET", "/service-categories", headers=headers, params=params)

    # ─── Customer ─────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ─── Pro ──────────────────────────────────────────────────
    def create_pro(self, payload, headers):
        return self._request("POST", "/pros", payload, headers)

    def get_pro(self, pro_id, headers):
        return self._request("GET", f"/pros/{pro_id}", headers=headers)

    def create_background_check(self, pro_id, payload, headers):
        return self._request("POST", f"/pros/{pro_id}/background-checks", payload, headers)

    def list_background_checks(self, pro_id, headers, params=None):
        return self._request("GET", f"/pros/{pro_id}/background-checks", headers=headers, params=params)

    def list_pro_dispatch_windows(self, pro_id, headers, params=None):
        return self._request("GET", f"/pros/{pro_id}/dispatch-windows", headers=headers, params=params)

    def list_pro_jobs(self, pro_id, headers, params=None):
        return self._request("GET", f"/pros/{pro_id}/jobs", headers=headers, params=params)

    # ─── BackgroundCheck decision ─────────────────────────────
    def decide_background_check(self, bc_id, payload, headers):
        return self._request("POST", f"/background-checks/{bc_id}/decide", payload, headers)

    # ─── Job ──────────────────────────────────────────────────
    def create_job(self, payload, headers):
        return self._request("POST", "/jobs", payload, headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/jobs", headers=headers, params=params)

    def instant_quote(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/instant-quote", {}, headers)

    def request_estimate(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/request-estimate", {}, headers)

    def submit_quote(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/quotes", payload, headers)

    def list_quotes(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/quotes", headers=headers, params=params)

    def accept_quote(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/accept-quote", payload, headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/cancel", {}, headers)

    def complete_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/complete", {}, headers)

    def open_callback(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/callbacks", {}, headers)

    def list_visits_for_job(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/visits", headers=headers, params=params)

    def create_visit(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/visits", payload, headers)

    def get_work_visit(self, visit_id, headers):
        return self._request("GET", f"/work-visits/{visit_id}", headers=headers)

    def list_work_visits(self, headers, params=None):
        return self._request("GET", "/work-visits", headers=headers, params=params)

    # ─── LaborLine ────────────────────────────────────────────
    def create_labor_line(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/labor-lines", payload, headers)

    def list_labor_lines(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/labor-lines", headers=headers, params=params)

    # ─── PartLine ─────────────────────────────────────────────
    def create_part_line(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/part-lines", payload, headers)

    def list_part_lines(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/part-lines", headers=headers, params=params)

    # ─── DispatchWindow ───────────────────────────────────────
    def create_dispatch_window(self, payload, headers):
        return self._request("POST", "/dispatch-windows", payload, headers)

    def get_dispatch_window(self, window_id, headers):
        return self._request("GET", f"/dispatch-windows/{window_id}", headers=headers)

    def list_dispatch_windows(self, headers, params=None):
        return self._request("GET", "/dispatch-windows", headers=headers, params=params)

    def book_window(self, window_id, payload, headers):
        return self._request("POST", f"/dispatch-windows/{window_id}/book", payload, headers)

    # ─── Invoice ──────────────────────────────────────────────
    def create_invoice(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/invoices", {}, headers)

    def list_invoices_for_job(self, job_id, headers, params=None):
        return self._request("GET", f"/jobs/{job_id}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", payload, headers)

    # ─── Dispute ──────────────────────────────────────────────
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/review", {}, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/withdraw", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    # ─── Test-only clock ──────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
