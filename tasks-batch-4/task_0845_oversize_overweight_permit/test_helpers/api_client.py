"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- reference data (DOTAdmin) ----
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    def deposit_escrow(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/escrow-deposits", payload, headers)

    def create_structure(self, payload, headers):
        return self._request("POST", "/structures", payload, headers)

    def get_structure(self, structure_id, headers):
        return self._request("GET", f"/structures/{structure_id}", headers=headers)

    def create_pilot_car(self, payload, headers):
        return self._request("POST", "/pilot-cars", payload, headers)

    def get_pilot_car(self, pilot_car_id, headers):
        return self._request("GET", f"/pilot-cars/{pilot_car_id}", headers=headers)

    def create_travel_restriction(self, payload, headers):
        return self._request("POST", "/travel-restrictions", payload, headers)

    # ---- permit lifecycle ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def edit_permit(self, permit_id, payload, headers):
        return self._request("PATCH", f"/permits/{permit_id}", payload, headers)

    def add_route_segment(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/route-segments", payload, headers)

    def list_route_segments(self, headers, params=None):
        return self._request("GET", "/route-segments", headers=headers, params=params)

    def get_route_segment(self, segment_id, headers):
        return self._request("GET", f"/route-segments/{segment_id}", headers=headers)

    def add_escort_assignment(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/escort-assignments", payload, headers)

    def list_escort_assignments(self, headers, params=None):
        return self._request("GET", "/escort-assignments", headers=headers, params=params)

    def get_escort_assignment(self, escort_id, headers):
        return self._request("GET", f"/escort-assignments/{escort_id}", headers=headers)

    def confirm_escort(self, escort_id, headers):
        return self._request("POST", f"/escort-assignments/{escort_id}/confirm", {}, headers)

    def cancel_escort(self, escort_id, headers):
        return self._request("POST", f"/escort-assignments/{escort_id}/cancel", {}, headers)

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/submit", {}, headers)

    def begin_review(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/begin-review", {}, headers)

    def return_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/permits/{permit_id}/return", payload or {}, headers)

    def approve_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/approve", {}, headers)

    def reject_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"/permits/{permit_id}/reject", payload or {}, headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/issue", {}, headers)

    def complete_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/complete", {}, headers)

    # ---- bridge analysis ----
    def list_bridge_analyses(self, headers, params=None):
        return self._request("GET", "/bridge-analyses", headers=headers, params=params)

    def get_bridge_analysis(self, ba_id, headers):
        return self._request("GET", f"/bridge-analyses/{ba_id}", headers=headers)

    def review_bridge_analysis(self, ba_id, payload, headers):
        return self._request("POST", f"/bridge-analyses/{ba_id}/review", payload, headers)

    def accept_conditions(self, ba_id, headers):
        return self._request("POST", f"/bridge-analyses/{ba_id}/accept-conditions", {}, headers)

    # ---- bonds ----
    def list_bonds(self, headers, params=None):
        return self._request("GET", "/bonds", headers=headers, params=params)

    def get_bond(self, bond_id, headers):
        return self._request("GET", f"/bonds/{bond_id}", headers=headers)

    # ---- violations ----
    def create_violation(self, payload, headers):
        return self._request("POST", "/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/violations", headers=headers, params=params)

    def contest_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/contest", {}, headers)

    def uphold_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/uphold", {}, headers)

    def dismiss_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/dismiss", {}, headers)

    # ---- clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
