"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Project ----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def create_estimate(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/estimates", payload, headers)

    def list_estimates(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/estimates", headers=headers, params=params)

    def approve_estimate(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/approve-estimate", payload, headers)

    def reject_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/reject", {}, headers)

    def schedule_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/schedule", {}, headers)

    def begin_cure(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/begin-cure", {}, headers)

    def complete_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/complete", {}, headers)

    def hold_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/hold", {}, headers)

    def resume_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/resume", {}, headers)

    # ---- FlatworkSegment ----
    def create_segment(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/segments", payload, headers)

    def list_segments(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/segments", headers=headers, params=params)

    # ---- Permit ----
    def create_permit(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/permits", payload, headers)

    def list_permits(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/permits", headers=headers, params=params)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/issue", {}, headers)

    def close_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/close", {}, headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", {}, headers)

    # ---- MaterialOrder ----
    def create_material_order(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/material-orders", payload, headers)

    def list_material_orders(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/material-orders", headers=headers, params=params)

    def get_material_order(self, material_order_id, headers):
        return self._request("GET", f"/material-orders/{material_order_id}", headers=headers)

    def start_pour(self, material_order_id, payload, headers):
        return self._request("POST", f"/material-orders/{material_order_id}/start-pour", payload, headers)

    def complete_pour(self, material_order_id, payload, headers):
        return self._request("POST", f"/material-orders/{material_order_id}/complete-pour", payload, headers)

    def cancel_material_order(self, material_order_id, headers):
        return self._request("POST", f"/material-orders/{material_order_id}/cancel", {}, headers)

    # ---- WeatherReading ----
    def create_weather_reading(self, material_order_id, payload, headers):
        return self._request("POST", f"/material-orders/{material_order_id}/weather-readings", payload, headers)

    def list_weather_readings(self, material_order_id, headers, params=None):
        return self._request("GET", f"/material-orders/{material_order_id}/weather-readings", headers=headers, params=params)

    # ---- Crew / Equipment ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    # ---- CrewAssignment ----
    def create_crew_assignment(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/crew-assignments", payload, headers)

    def list_project_crew_assignments(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/crew-assignments", headers=headers, params=params)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/crew-assignments", headers=headers, params=params)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"/crew-assignments/{assignment_id}", headers=headers)

    def release_crew_assignment(self, assignment_id, headers):
        return self._request("POST", f"/crew-assignments/{assignment_id}/release", {}, headers)

    # ---- ChangeOrder ----
    def create_change_order(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/change-orders", payload, headers)

    def list_change_orders(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/change-orders", headers=headers, params=params)

    def start_review_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/start-review", {}, headers)

    def request_revision_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/request-revision", {}, headers)

    def resubmit_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/resubmit", payload, headers)

    def approve_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/approve", payload, headers)

    def reject_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/reject", {}, headers)

    # ---- Draw ----
    def create_draw(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/draws", payload, headers)

    def list_draws(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/draws", headers=headers, params=params)

    def release_draw(self, draw_id, payload, headers):
        return self._request("POST", f"/draws/{draw_id}/release", payload, headers)

    def void_draw(self, draw_id, headers):
        return self._request("POST", f"/draws/{draw_id}/void", {}, headers)

    # ---- Warranty ----
    def create_warranty(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/warranties", payload, headers)

    def list_warranties(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/warranties", headers=headers, params=params)

    def file_claim(self, warranty_id, payload, headers):
        return self._request("POST", f"/warranties/{warranty_id}/claims", payload, headers)

    def resolve_claim(self, warranty_id, headers):
        return self._request("POST", f"/warranties/{warranty_id}/resolve-claim", {}, headers)

    def void_warranty(self, warranty_id, headers):
        return self._request("POST", f"/warranties/{warranty_id}/void", {}, headers)

    # ---- test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
