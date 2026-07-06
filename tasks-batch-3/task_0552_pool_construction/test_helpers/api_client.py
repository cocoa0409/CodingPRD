"""API client: one method per Pool Construction endpoint (PRD §4).

Subclasses the framework GenericApiClient; the base _request() handles the HTTP
mechanics and envelope transport. All paths are peer-mounted under /pool-build.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- PoolProject ---
    def create_pool_project(self, payload, headers):
        return self._request("POST", "/pool-build/pool-projects", payload, headers)

    def get_pool_project(self, project_id, headers):
        return self._request("GET", f"/pool-build/pool-projects/{project_id}", headers=headers)

    def transition_pool_project(self, project_id, payload, headers):
        return self._request("POST", f"/pool-build/pool-projects/{project_id}/transition", payload, headers)

    # --- DesignPlan ---
    def create_design_plan(self, payload, headers):
        return self._request("POST", "/pool-build/design-plans", payload, headers)

    def get_design_plan(self, design_plan_id, headers):
        return self._request("GET", f"/pool-build/design-plans/{design_plan_id}", headers=headers)

    def list_design_plans(self, headers, params=None):
        return self._request("GET", "/pool-build/design-plans", headers=headers, params=params)

    def transition_design_plan(self, design_plan_id, payload, headers):
        return self._request("POST", f"/pool-build/design-plans/{design_plan_id}/transition", payload, headers)

    # --- PhaseGate ---
    def create_phase_gate(self, payload, headers):
        return self._request("POST", "/pool-build/phase-gates", payload, headers)

    def get_phase_gate(self, phase_gate_id, headers):
        return self._request("GET", f"/pool-build/phase-gates/{phase_gate_id}", headers=headers)

    def list_phase_gates(self, headers, params=None):
        return self._request("GET", "/pool-build/phase-gates", headers=headers, params=params)

    def start_phase_gate(self, phase_gate_id, headers):
        return self._request("POST", f"/pool-build/phase-gates/{phase_gate_id}/start", {}, headers)

    # --- Inspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/pool-build/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/pool-build/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/pool-build/inspections", headers=headers, params=params)

    def record_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/pool-build/inspections/{inspection_id}/record", payload, headers)

    # --- Subcontractor ---
    def create_subcontractor(self, payload, headers):
        return self._request("POST", "/pool-build/subcontractors", payload, headers)

    def get_subcontractor(self, subcontractor_id, headers):
        return self._request("GET", f"/pool-build/subcontractors/{subcontractor_id}", headers=headers)

    def transition_subcontractor(self, subcontractor_id, payload, headers):
        return self._request("POST", f"/pool-build/subcontractors/{subcontractor_id}/transition", payload, headers)

    # --- CrewAssignment ---
    def create_crew_assignment(self, payload, headers):
        return self._request("POST", "/pool-build/crew-assignments", payload, headers)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"/pool-build/crew-assignments/{assignment_id}", headers=headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/pool-build/crew-assignments", headers=headers, params=params)

    def transition_crew_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/pool-build/crew-assignments/{assignment_id}/transition", payload, headers)

    # --- ChangeOrder ---
    def create_change_order(self, payload, headers):
        return self._request("POST", "/pool-build/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/pool-build/change-orders/{change_order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/pool-build/change-orders", headers=headers, params=params)

    def transition_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/pool-build/change-orders/{change_order_id}/transition", payload, headers)

    # --- DrawRequest ---
    def create_draw_request(self, payload, headers):
        return self._request("POST", "/pool-build/draw-requests", payload, headers)

    def get_draw_request(self, draw_request_id, headers):
        return self._request("GET", f"/pool-build/draw-requests/{draw_request_id}", headers=headers)

    def list_draw_requests(self, headers, params=None):
        return self._request("GET", "/pool-build/draw-requests", headers=headers, params=params)

    def transition_draw_request(self, draw_request_id, payload, headers):
        return self._request("POST", f"/pool-build/draw-requests/{draw_request_id}/transition", payload, headers)

    # --- PunchItem ---
    def create_punch_item(self, payload, headers):
        return self._request("POST", "/pool-build/punch-items", payload, headers)

    def get_punch_item(self, punch_item_id, headers):
        return self._request("GET", f"/pool-build/punch-items/{punch_item_id}", headers=headers)

    def list_punch_items(self, headers, params=None):
        return self._request("GET", "/pool-build/punch-items", headers=headers, params=params)

    def resolve_punch_item(self, punch_item_id, payload, headers):
        return self._request("POST", f"/pool-build/punch-items/{punch_item_id}/resolve", payload, headers)

    # --- Logical clock (test-driving utility, PRD §2.9) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
