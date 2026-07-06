"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_product_line_items(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/line-items", headers=headers, params=params)

    def list_product_change_orders(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/change-orders", headers=headers, params=params)

    # ---- Crew ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def list_crew_work_phases(self, crew_id, headers, params=None):
        return self._request("GET", f"/crews/{crew_id}/work-phases", headers=headers, params=params)

    # ---- Project ----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def generate_estimate(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/generate-estimate", {}, headers)

    def submit_approvals(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/submit-approvals", {}, headers)

    def sign_contract(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/sign-contract", {}, headers)

    def start_production(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/start-production", {}, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", {}, headers)

    # ---- DesignRevision ----
    def create_design_revision(self, payload, headers):
        return self._request("POST", "/design-revisions", payload, headers)

    def get_design_revision(self, revision_id, headers):
        return self._request("GET", f"/design-revisions/{revision_id}", headers=headers)

    def list_project_design_revisions(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/design-revisions", headers=headers, params=params)

    def render_design(self, revision_id, headers):
        return self._request("POST", f"/design-revisions/{revision_id}/render", {}, headers)

    def submit_review(self, revision_id, headers):
        return self._request("POST", f"/design-revisions/{revision_id}/submit-review", {}, headers)

    def approve_design(self, revision_id, headers):
        return self._request("POST", f"/design-revisions/{revision_id}/approve", {}, headers)

    def request_revision(self, revision_id, headers):
        return self._request("POST", f"/design-revisions/{revision_id}/request-revision", {}, headers)

    def revise_design(self, revision_id, headers):
        return self._request("POST", f"/design-revisions/{revision_id}/revise", {}, headers)

    # ---- SiteMeasurement ----
    def create_site_measurement(self, payload, headers):
        return self._request("POST", "/site-measurements", payload, headers)

    def get_site_measurement(self, measurement_id, headers):
        return self._request("GET", f"/site-measurements/{measurement_id}", headers=headers)

    def list_project_site_measurements(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/site-measurements", headers=headers, params=params)

    # ---- LineItem ----
    def create_line_item(self, payload, headers):
        return self._request("POST", "/line-items", payload, headers)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/line-items/{line_item_id}", headers=headers)

    def list_project_line_items(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/line-items", headers=headers, params=params)

    # ---- Permit ----
    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_project_permits(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/permits", headers=headers, params=params)

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/submit", {}, headers)

    def approve_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/approve", {}, headers)

    def deny_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/deny", payload, headers)

    # ---- HoaSubmission ----
    def get_hoa_submission(self, hoa_id, headers):
        return self._request("GET", f"/hoa-submissions/{hoa_id}", headers=headers)

    def list_project_hoa_submissions(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/hoa-submissions", headers=headers, params=params)

    def submit_hoa(self, hoa_id, headers):
        return self._request("POST", f"/hoa-submissions/{hoa_id}/submit", {}, headers)

    def decide_hoa(self, hoa_id, payload, headers):
        return self._request("POST", f"/hoa-submissions/{hoa_id}/decide", payload, headers)

    # ---- ChangeOrder ----
    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def list_project_change_orders(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/change-orders", headers=headers, params=params)

    def approve_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/approve", {}, headers)

    def reject_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/reject", {}, headers)

    # ---- MaterialOrder ----
    def create_material_order(self, payload, headers):
        return self._request("POST", "/material-orders", payload, headers)

    def get_material_order(self, order_id, headers):
        return self._request("GET", f"/material-orders/{order_id}", headers=headers)

    def list_project_material_orders(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/material-orders", headers=headers, params=params)

    def place_material_order(self, order_id, headers):
        return self._request("POST", f"/material-orders/{order_id}/place", {}, headers)

    def confirm_delivery(self, order_id, headers):
        return self._request("POST", f"/material-orders/{order_id}/confirm-delivery", {}, headers)

    # ---- WorkPhase ----
    def create_work_phase(self, payload, headers):
        return self._request("POST", "/work-phases", payload, headers)

    def get_work_phase(self, phase_id, headers):
        return self._request("GET", f"/work-phases/{phase_id}", headers=headers)

    def list_project_work_phases(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/work-phases", headers=headers, params=params)

    def schedule_work_phase(self, phase_id, payload, headers):
        return self._request("POST", f"/work-phases/{phase_id}/schedule", payload, headers)

    def start_work_phase(self, phase_id, headers):
        return self._request("POST", f"/work-phases/{phase_id}/start", {}, headers)

    def complete_work_phase(self, phase_id, payload, headers):
        return self._request("POST", f"/work-phases/{phase_id}/complete", payload, headers)

    # ---- ProgressDraw ----
    def create_draw(self, payload, headers):
        return self._request("POST", "/draws", payload, headers)

    def get_draw(self, draw_id, headers):
        return self._request("GET", f"/draws/{draw_id}", headers=headers)

    def list_project_draws(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/draws", headers=headers, params=params)

    def list_work_phase_draws(self, phase_id, headers, params=None):
        return self._request("GET", f"/work-phases/{phase_id}/draws", headers=headers, params=params)

    def record_payment(self, draw_id, headers):
        return self._request("POST", f"/draws/{draw_id}/record-payment", {}, headers)

    def refund_draw(self, draw_id, headers):
        return self._request("POST", f"/draws/{draw_id}/refund", {}, headers)

    # ---- WarrantyClaim ----
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def list_project_warranty_claims(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/warranty-claims", headers=headers, params=params)

    def decide_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/decide", payload, headers)


api_client = ApiClient()
