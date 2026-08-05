"""API client: one method per endpoint defined in the PRD (Section 4).

Subclasses ``GenericApiClient``; the base ``_request()`` handles the HTTP call,
envelope, and base URL. Only PRD-specific endpoint methods are declared here.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/access/_clock/set_current_utc", payload, headers)

    # --- Community ---
    def create_community(self, payload, headers):
        return self._request("POST", "/access/communities", payload, headers)

    def get_community(self, community_id, headers):
        return self._request("GET", f"/access/communities/{community_id}", headers=headers)

    # --- Resident ---
    def create_resident(self, payload, headers):
        return self._request("POST", "/access/residents", payload, headers)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/access/residents/{resident_id}", headers=headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", "/access/residents", headers=headers, params=params)

    def transition_resident(self, resident_id, payload, headers):
        return self._request("POST", f"/access/residents/{resident_id}/transition", payload, headers)

    def get_resident_statement(self, resident_id, headers):
        return self._request("GET", f"/access/residents/{resident_id}/statement", headers=headers)

    # --- Vehicle ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/access/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/access/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/access/vehicles", headers=headers, params=params)

    def transition_vehicle(self, vehicle_id, payload, headers):
        return self._request("POST", f"/access/vehicles/{vehicle_id}/transition", payload, headers)

    # --- Decal ---
    def create_decal(self, payload, headers):
        return self._request("POST", "/access/decals", payload, headers)

    def get_decal(self, decal_id, headers):
        return self._request("GET", f"/access/decals/{decal_id}", headers=headers)

    def list_decals(self, headers, params=None):
        return self._request("GET", "/access/decals", headers=headers, params=params)

    def transition_decal(self, decal_id, payload, headers):
        return self._request("POST", f"/access/decals/{decal_id}/transition", payload, headers)

    # --- Pass ---
    def create_pass(self, payload, headers):
        return self._request("POST", "/access/passes", payload, headers)

    def get_pass(self, pass_id, headers):
        return self._request("GET", f"/access/passes/{pass_id}", headers=headers)

    def list_passes(self, headers, params=None):
        return self._request("GET", "/access/passes", headers=headers, params=params)

    def authorize_pass(self, pass_id, payload, headers):
        return self._request("POST", f"/access/passes/{pass_id}/authorize", payload, headers)

    def revoke_pass(self, pass_id, headers):
        return self._request("POST", f"/access/passes/{pass_id}/revoke", None, headers)

    # --- GateEvent ---
    def create_gate_event(self, payload, headers):
        return self._request("POST", "/access/gate-events", payload, headers)

    def get_gate_event(self, gate_event_id, headers):
        return self._request("GET", f"/access/gate-events/{gate_event_id}", headers=headers)

    def list_gate_events(self, headers, params=None):
        return self._request("GET", "/access/gate-events", headers=headers, params=params)

    # --- Amenity ---
    def create_amenity(self, payload, headers):
        return self._request("POST", "/access/amenities", payload, headers)

    def get_amenity(self, amenity_id, headers):
        return self._request("GET", f"/access/amenities/{amenity_id}", headers=headers)

    def list_amenities(self, headers, params=None):
        return self._request("GET", "/access/amenities", headers=headers, params=params)

    # --- AmenityReservation ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/access/amenity-reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/access/amenity-reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/access/amenity-reservations", headers=headers, params=params)

    def transition_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/access/amenity-reservations/{reservation_id}/transition", payload, headers)

    # --- Patrol ---
    def create_patrol(self, payload, headers):
        return self._request("POST", "/access/patrols", payload, headers)

    def get_patrol(self, patrol_id, headers):
        return self._request("GET", f"/access/patrols/{patrol_id}", headers=headers)

    def list_patrols(self, headers, params=None):
        return self._request("GET", "/access/patrols", headers=headers, params=params)

    def transition_patrol(self, patrol_id, payload, headers):
        return self._request("POST", f"/access/patrols/{patrol_id}/transition", payload, headers)

    # --- Incident ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/access/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/access/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/access/incidents", headers=headers, params=params)

    def transition_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/access/incidents/{incident_id}/transition", payload, headers)

    # --- Violation ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/access/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/access/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/access/violations", headers=headers, params=params)

    def appeal_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/access/violations/{violation_id}/appeal", payload, headers)

    def withdraw_appeal_violation(self, violation_id, headers):
        return self._request("POST", f"/access/violations/{violation_id}/withdraw-appeal", None, headers)

    def resolve_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/access/violations/{violation_id}/resolve", payload, headers)

    def pay_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/access/violations/{violation_id}/pay", payload, headers)

    # --- Reports ---
    def get_access_log_report(self, community_id, headers, params=None):
        return self._request("GET", f"/access/communities/{community_id}/reports/access-log", headers=headers, params=params)

    def get_violations_summary_report(self, community_id, headers):
        return self._request("GET", f"/access/communities/{community_id}/reports/violations-summary", headers=headers)


api_client = ApiClient()
