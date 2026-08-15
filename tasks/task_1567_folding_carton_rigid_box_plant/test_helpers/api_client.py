"""API client: one method per endpoint defined in the PRD (all under /plant)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/plant/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/plant/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/plant/customers/{customer_id}", headers=headers)

    def set_customer_status(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/plant/customers/{customer_id}/set-status", payload, headers
        )

    # --- ColorStandard ---
    def create_color_standard(self, payload, headers):
        return self._request("POST", "/plant/color-standards", payload, headers)

    def list_color_standards(self, headers, params=None):
        return self._request(
            "GET", "/plant/color-standards", headers=headers, params=params
        )

    def get_color_standard(self, standard_id, headers):
        return self._request(
            "GET", f"/plant/color-standards/{standard_id}", headers=headers
        )

    def submit_color_standard(self, standard_id, headers):
        return self._request(
            "POST", f"/plant/color-standards/{standard_id}/submit", {}, headers
        )

    def approve_color_standard(self, standard_id, headers):
        return self._request(
            "POST", f"/plant/color-standards/{standard_id}/approve", {}, headers
        )

    # --- Job ---
    def create_job(self, payload, headers):
        return self._request("POST", "/plant/jobs", payload, headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/plant/jobs", headers=headers, params=params)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/plant/jobs/{job_id}", headers=headers)

    def start_engineering(self, job_id, headers):
        return self._request(
            "POST", f"/plant/jobs/{job_id}/start-engineering", {}, headers
        )

    def mark_press_ready(self, job_id, headers):
        return self._request(
            "POST", f"/plant/jobs/{job_id}/mark-press-ready", {}, headers
        )

    def start_production(self, job_id, headers):
        return self._request(
            "POST", f"/plant/jobs/{job_id}/start-production", {}, headers
        )

    def complete_press(self, job_id, headers):
        return self._request("POST", f"/plant/jobs/{job_id}/complete-press", {}, headers)

    def complete_finishing(self, job_id, headers):
        return self._request(
            "POST", f"/plant/jobs/{job_id}/complete-finishing", {}, headers
        )

    def complete_job(self, job_id, headers):
        return self._request("POST", f"/plant/jobs/{job_id}/complete", {}, headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/plant/jobs/{job_id}/cancel", {}, headers)

    # --- DesignRevision ---
    def create_design_revision(self, payload, headers):
        return self._request("POST", "/plant/design-revisions", payload, headers)

    def list_design_revisions(self, headers, params=None):
        return self._request(
            "GET", "/plant/design-revisions", headers=headers, params=params
        )

    def get_design_revision(self, revision_id, headers):
        return self._request(
            "GET", f"/plant/design-revisions/{revision_id}", headers=headers
        )

    def make_sample(self, revision_id, headers):
        return self._request(
            "POST", f"/plant/design-revisions/{revision_id}/make-sample", {}, headers
        )

    def brand_accept_revision(self, revision_id, headers):
        return self._request(
            "POST", f"/plant/design-revisions/{revision_id}/brand-accept", {}, headers
        )

    def brand_reject_revision(self, revision_id, headers):
        return self._request(
            "POST", f"/plant/design-revisions/{revision_id}/brand-reject", {}, headers
        )

    # --- ImpositionPlan ---
    def create_imposition_plan(self, payload, headers):
        return self._request("POST", "/plant/imposition-plans", payload, headers)

    def list_imposition_plans(self, headers, params=None):
        return self._request(
            "GET", "/plant/imposition-plans", headers=headers, params=params
        )

    def get_imposition_plan(self, plan_id, headers):
        return self._request("GET", f"/plant/imposition-plans/{plan_id}", headers=headers)

    def lock_imposition_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/plant/imposition-plans/{plan_id}/lock", payload, headers
        )

    def supersede_imposition_plan(self, plan_id, headers):
        return self._request(
            "POST", f"/plant/imposition-plans/{plan_id}/supersede", {}, headers
        )

    # --- PressApproval ---
    def create_press_approval(self, payload, headers):
        return self._request("POST", "/plant/press-approvals", payload, headers)

    def list_press_approvals(self, headers, params=None):
        return self._request(
            "GET", "/plant/press-approvals", headers=headers, params=params
        )

    def get_press_approval(self, approval_id, headers):
        return self._request(
            "GET", f"/plant/press-approvals/{approval_id}", headers=headers
        )

    def approve_press_approval(self, approval_id, headers):
        return self._request(
            "POST", f"/plant/press-approvals/{approval_id}/approve", {}, headers
        )

    def reject_press_approval(self, approval_id, headers):
        return self._request(
            "POST", f"/plant/press-approvals/{approval_id}/reject", {}, headers
        )

    def resubmit_press_approval(self, approval_id, payload, headers):
        return self._request(
            "POST", f"/plant/press-approvals/{approval_id}/resubmit", payload, headers
        )

    # --- Press ---
    def create_press(self, payload, headers):
        return self._request("POST", "/plant/presses", payload, headers)

    def list_presses(self, headers, params=None):
        return self._request("GET", "/plant/presses", headers=headers, params=params)

    def get_press(self, press_id, headers):
        return self._request("GET", f"/plant/presses/{press_id}", headers=headers)

    def set_press_status(self, press_id, payload, headers):
        return self._request(
            "POST", f"/plant/presses/{press_id}/set-status", payload, headers
        )

    # --- PressBooking ---
    def create_press_booking(self, payload, headers):
        return self._request("POST", "/plant/press-bookings", payload, headers)

    def list_press_bookings(self, headers, params=None):
        return self._request(
            "GET", "/plant/press-bookings", headers=headers, params=params
        )

    def get_press_booking(self, booking_id, headers):
        return self._request(
            "GET", f"/plant/press-bookings/{booking_id}", headers=headers
        )

    def complete_press_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/plant/press-bookings/{booking_id}/complete", payload, headers
        )

    def cancel_press_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/plant/press-bookings/{booking_id}/cancel", {}, headers
        )

    # --- FinishingLine ---
    def create_finishing_line(self, payload, headers):
        return self._request("POST", "/plant/finishing-lines", payload, headers)

    def list_finishing_lines(self, headers, params=None):
        return self._request(
            "GET", "/plant/finishing-lines", headers=headers, params=params
        )

    def get_finishing_line(self, line_id, headers):
        return self._request("GET", f"/plant/finishing-lines/{line_id}", headers=headers)

    def set_finishing_line_status(self, line_id, payload, headers):
        return self._request(
            "POST", f"/plant/finishing-lines/{line_id}/set-status", payload, headers
        )

    # --- FinishingBooking ---
    def create_finishing_booking(self, payload, headers):
        return self._request("POST", "/plant/finishing-bookings", payload, headers)

    def list_finishing_bookings(self, headers, params=None):
        return self._request(
            "GET", "/plant/finishing-bookings", headers=headers, params=params
        )

    def get_finishing_booking(self, booking_id, headers):
        return self._request(
            "GET", f"/plant/finishing-bookings/{booking_id}", headers=headers
        )

    def complete_finishing_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/plant/finishing-bookings/{booking_id}/complete", {}, headers
        )

    def cancel_finishing_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/plant/finishing-bookings/{booking_id}/cancel", {}, headers
        )

    # --- BoardStock ---
    def create_board_stock(self, payload, headers):
        return self._request("POST", "/plant/board-stocks", payload, headers)

    def list_board_stocks(self, headers, params=None):
        return self._request("GET", "/plant/board-stocks", headers=headers, params=params)

    def get_board_stock(self, stock_id, headers):
        return self._request("GET", f"/plant/board-stocks/{stock_id}", headers=headers)

    def receive_board_stock(self, stock_id, payload, headers):
        return self._request(
            "POST", f"/plant/board-stocks/{stock_id}/receive", payload, headers
        )

    # --- KitOrder ---
    def create_kit_order(self, payload, headers):
        return self._request("POST", "/plant/kit-orders", payload, headers)

    def list_kit_orders(self, headers, params=None):
        return self._request("GET", "/plant/kit-orders", headers=headers, params=params)

    def get_kit_order(self, kit_id, headers):
        return self._request("GET", f"/plant/kit-orders/{kit_id}", headers=headers)

    def start_kit_order(self, kit_id, headers):
        return self._request("POST", f"/plant/kit-orders/{kit_id}/start", {}, headers)

    def complete_kit_order(self, kit_id, payload, headers):
        return self._request(
            "POST", f"/plant/kit-orders/{kit_id}/complete", payload, headers
        )

    def cancel_kit_order(self, kit_id, headers):
        return self._request("POST", f"/plant/kit-orders/{kit_id}/cancel", {}, headers)

    # --- RetailReadyAudit ---
    def create_retail_audit(self, payload, headers):
        return self._request("POST", "/plant/retail-audits", payload, headers)

    def list_retail_audits(self, headers, params=None):
        return self._request("GET", "/plant/retail-audits", headers=headers, params=params)

    def get_retail_audit(self, audit_id, headers):
        return self._request("GET", f"/plant/retail-audits/{audit_id}", headers=headers)

    def submit_retail_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/plant/retail-audits/{audit_id}/submit", {}, headers
        )

    def certify_retail_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/plant/retail-audits/{audit_id}/certify", {}, headers
        )

    def reject_retail_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/plant/retail-audits/{audit_id}/reject", {}, headers
        )

    def revise_retail_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/plant/retail-audits/{audit_id}/revise", payload, headers
        )

    # --- Invoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/plant/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/plant/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/plant/invoices/{invoice_id}", headers=headers)

    def finalize_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/plant/invoices/{invoice_id}/finalize", {}, headers
        )

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/plant/invoices/{invoice_id}/void", {}, headers)

    def settle_invoice(self, invoice_id, headers):
        return self._request("POST", f"/plant/invoices/{invoice_id}/settle", {}, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/plant/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
