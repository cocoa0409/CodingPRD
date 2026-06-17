"""API client: one method per endpoint defined in the Roofing Storm
Restoration PRD (§4). Subclasses the framework GenericApiClient; the base
_request() method handles envelope plumbing.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Estimator (reference data) ----
    def create_estimator(self, payload, headers):
        return self._request("POST", "/estimators", payload, headers)

    def get_estimator(self, estimator_id, headers):
        return self._request("GET", f"/estimators/{estimator_id}", headers=headers)

    # ---- Crew (reference data) ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    # ---- Job ----
    def create_job(self, payload, headers):
        return self._request("POST", "/jobs", payload, headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/jobs", headers=headers, params=params)

    def mark_job_inspected(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/mark-inspected", {}, headers)

    def mark_job_estimated(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/mark-estimated", {}, headers)

    def contract_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/contract", payload, headers)

    def start_production(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/start-production", {}, headers)

    def complete_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/complete", {}, headers)

    def lose_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/lose", payload, headers)

    # ---- Inspection ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/complete", payload, headers)

    # ---- Estimate ----
    def create_estimate(self, payload, headers):
        return self._request("POST", "/estimates", payload, headers)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/estimates/{estimate_id}", headers=headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/estimates", headers=headers, params=params)

    def add_line_item(self, estimate_id, payload, headers):
        return self._request("POST", f"/estimates/{estimate_id}/line-items", payload, headers)

    def list_line_items(self, estimate_id, headers, params=None):
        return self._request("GET", f"/estimates/{estimate_id}/line-items", headers=headers, params=params)

    def finalize_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/finalize", {}, headers)

    # ---- MaterialOrder ----
    def create_material_order(self, payload, headers):
        return self._request("POST", "/material-orders", payload, headers)

    def get_material_order(self, order_id, headers):
        return self._request("GET", f"/material-orders/{order_id}", headers=headers)

    def list_material_orders(self, headers, params=None):
        return self._request("GET", "/material-orders", headers=headers, params=params)

    def deliver_material_order(self, order_id, payload, headers):
        return self._request("POST", f"/material-orders/{order_id}/deliver", payload, headers)

    def cancel_material_order(self, order_id, headers):
        return self._request("POST", f"/material-orders/{order_id}/cancel", {}, headers)

    # ---- CrewAssignment ----
    def create_crew_assignment(self, payload, headers):
        return self._request("POST", "/crew-assignments", payload, headers)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"/crew-assignments/{assignment_id}", headers=headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/crew-assignments", headers=headers, params=params)

    def check_in_crew_assignment(self, assignment_id, headers):
        return self._request("POST", f"/crew-assignments/{assignment_id}/check-in", {}, headers)

    def complete_crew_assignment(self, assignment_id, headers):
        return self._request("POST", f"/crew-assignments/{assignment_id}/complete", {}, headers)

    def cancel_crew_assignment(self, assignment_id, headers):
        return self._request("POST", f"/crew-assignments/{assignment_id}/cancel", {}, headers)

    # ---- Permit ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def issue_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/issue", payload, headers)

    def expire_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/expire", {}, headers)

    # ---- Draw ----
    def create_draw(self, payload, headers):
        return self._request("POST", "/draws", payload, headers)

    def get_draw(self, draw_id, headers):
        return self._request("GET", f"/draws/{draw_id}", headers=headers)

    def list_draws(self, headers, params=None):
        return self._request("GET", "/draws", headers=headers, params=params)

    # ---- ChangeOrder ----
    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/change-orders", headers=headers, params=params)

    def approve_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/approve", {}, headers)

    def apply_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/apply", payload, headers)

    def void_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/void", {}, headers)

    # ---- Warranty ----
    def create_warranty(self, payload, headers):
        return self._request("POST", "/warranties", payload, headers)

    def get_warranty(self, warranty_id, headers):
        return self._request("GET", f"/warranties/{warranty_id}", headers=headers)

    def list_warranties(self, headers, params=None):
        return self._request("GET", "/warranties", headers=headers, params=params)

    def activate_warranty(self, warranty_id, headers):
        return self._request("POST", f"/warranties/{warranty_id}/activate", {}, headers)

    def cancel_warranty(self, warranty_id, payload, headers):
        return self._request("POST", f"/warranties/{warranty_id}/cancel", payload, headers)

    def expire_warranty(self, warranty_id, headers):
        return self._request("POST", f"/warranties/{warranty_id}/expire", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)


api_client = ApiClient()
