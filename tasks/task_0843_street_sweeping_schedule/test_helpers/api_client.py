"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() handles the HTTP envelope.
All business paths are prefixed with /api; the logical clock lives at /_clock.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Route ---
    def create_route(self, payload, headers):
        return self._request("POST", "/api/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/api/routes/{route_id}", headers=headers)

    # --- Block ---
    def create_block(self, payload, headers):
        return self._request("POST", "/api/blocks", payload, headers)

    def get_block(self, block_id, headers):
        return self._request("GET", f"/api/blocks/{block_id}", headers=headers)

    def list_blocks(self, headers, params=None):
        return self._request("GET", "/api/blocks", headers=headers, params=params)

    def post_sign(self, block_id, payload, headers):
        return self._request("POST", f"/api/blocks/{block_id}/post-sign", payload, headers)

    def verify_sign(self, block_id, headers):
        return self._request("POST", f"/api/blocks/{block_id}/verify-sign", {}, headers)

    # --- Equipment ---
    def create_equipment(self, payload, headers):
        return self._request("POST", "/api/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/api/equipment/{equipment_id}", headers=headers)

    # --- Shift ---
    def create_shift(self, payload, headers):
        return self._request("POST", "/api/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/api/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/api/shifts", headers=headers, params=params)

    def start_shift(self, shift_id, headers):
        return self._request("POST", f"/api/shifts/{shift_id}/start", {}, headers)

    def close_shift(self, shift_id, headers):
        return self._request("POST", f"/api/shifts/{shift_id}/close", {}, headers)

    # --- SweepEvent ---
    def create_sweep_event(self, payload, headers):
        return self._request("POST", "/api/sweep-events", payload, headers)

    def get_sweep_event(self, event_id, headers):
        return self._request("GET", f"/api/sweep-events/{event_id}", headers=headers)

    def list_sweep_events(self, headers, params=None):
        return self._request("GET", "/api/sweep-events", headers=headers, params=params)

    def complete_sweep_event(self, event_id, payload, headers):
        return self._request("POST", f"/api/sweep-events/{event_id}/complete", payload, headers)

    def miss_sweep_event(self, event_id, payload, headers):
        return self._request("POST", f"/api/sweep-events/{event_id}/miss", payload, headers)

    def void_sweep_event(self, event_id, payload, headers):
        return self._request("POST", f"/api/sweep-events/{event_id}/void", payload, headers)

    def notify_sweep_event(self, event_id, payload, headers):
        return self._request("POST", f"/api/sweep-events/{event_id}/notify", payload, headers)

    # --- Suspension ---
    def create_suspension(self, payload, headers):
        return self._request("POST", "/api/suspensions", payload, headers)

    def get_suspension(self, suspension_id, headers):
        return self._request("GET", f"/api/suspensions/{suspension_id}", headers=headers)

    def list_suspensions(self, headers, params=None):
        return self._request("GET", "/api/suspensions", headers=headers, params=params)

    def activate_suspension(self, suspension_id, headers):
        return self._request("POST", f"/api/suspensions/{suspension_id}/activate", {}, headers)

    def lift_suspension(self, suspension_id, headers):
        return self._request("POST", f"/api/suspensions/{suspension_id}/lift", {}, headers)

    # --- Citation ---
    def create_citation(self, payload, headers):
        return self._request("POST", "/api/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/api/citations/{citation_id}", headers=headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/api/citations", headers=headers, params=params)

    def contest_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/api/citations/{citation_id}/contest", payload, headers)

    def adjudicate_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/api/citations/{citation_id}/adjudicate", payload, headers)

    def pay_citation(self, citation_id, headers):
        return self._request("POST", f"/api/citations/{citation_id}/pay", {}, headers)

    # --- Resident ---
    def create_resident(self, payload, headers):
        return self._request("POST", "/api/residents", payload, headers)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/api/residents/{resident_id}", headers=headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", "/api/residents", headers=headers, params=params)

    # --- Complaint ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/api/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/api/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/api/complaints", headers=headers, params=params)

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/api/complaints/{complaint_id}/resolve", payload, headers)

    def reject_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/api/complaints/{complaint_id}/reject", payload, headers)

    def reopen_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/api/complaints/{complaint_id}/reopen", payload, headers)


api_client = ApiClient()
