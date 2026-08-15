"""API client: one method per endpoint defined in the PRD endpoint table.

All endpoints are mounted under the /charter prefix (PRD section 1).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/charter/_clock/set_current_utc", payload, headers)

    # --- Aircraft owners ---
    def create_aircraft_owner(self, payload, headers):
        return self._request("POST", "/charter/aircraft-owners", payload, headers)

    def list_aircraft_owners(self, headers, params=None):
        return self._request("GET", "/charter/aircraft-owners", headers=headers, params=params)

    def get_aircraft_owner(self, owner_id, headers):
        return self._request("GET", f"/charter/aircraft-owners/{owner_id}", headers=headers)

    # --- Aircraft ---
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/charter/aircraft", payload, headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/charter/aircraft", headers=headers, params=params)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/charter/aircraft/{aircraft_id}", headers=headers)

    def ground_aircraft(self, aircraft_id, headers):
        return self._request("POST", f"/charter/aircraft/{aircraft_id}/ground", headers=headers)

    def return_aircraft_to_service(self, aircraft_id, headers):
        return self._request("POST", f"/charter/aircraft/{aircraft_id}/return-to-service", headers=headers)

    # --- Crew members ---
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/charter/crew-members", payload, headers)

    def list_crew_members(self, headers, params=None):
        return self._request("GET", "/charter/crew-members", headers=headers, params=params)

    def get_crew_member(self, crew_member_id, headers):
        return self._request("GET", f"/charter/crew-members/{crew_member_id}", headers=headers)

    def patch_crew_member(self, crew_member_id, payload, headers):
        return self._request("PATCH", f"/charter/crew-members/{crew_member_id}", payload, headers)

    # --- Trip requests ---
    def create_trip_request(self, payload, headers):
        return self._request("POST", "/charter/trip-requests", payload, headers)

    def list_trip_requests(self, headers, params=None):
        return self._request("GET", "/charter/trip-requests", headers=headers, params=params)

    def get_trip_request(self, trip_id, headers):
        return self._request("GET", f"/charter/trip-requests/{trip_id}", headers=headers)

    def quote_trip(self, trip_id, headers):
        return self._request("POST", f"/charter/trip-requests/{trip_id}/quote", headers=headers)

    def requote_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/charter/trip-requests/{trip_id}/requote", payload, headers)

    def book_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/charter/trip-requests/{trip_id}/book", payload, headers)

    def cancel_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/charter/trip-requests/{trip_id}/cancel", payload, headers)

    def dispatch_trip(self, trip_id, headers):
        return self._request("POST", f"/charter/trip-requests/{trip_id}/dispatch", headers=headers)

    # --- Quote legs ---
    def create_quote_leg(self, payload, headers):
        return self._request("POST", "/charter/quote-legs", payload, headers)

    def get_quote_leg(self, leg_id, headers):
        return self._request("GET", f"/charter/quote-legs/{leg_id}", headers=headers)

    def list_quote_legs(self, trip_id, headers, params=None):
        return self._request("GET", f"/charter/trip-requests/{trip_id}/quote-legs", headers=headers, params=params)

    def delete_quote_leg(self, leg_id, headers):
        return self._request("DELETE", f"/charter/quote-legs/{leg_id}", headers=headers)

    # --- Aircraft assignments ---
    def create_aircraft_assignment(self, payload, headers):
        return self._request("POST", "/charter/aircraft-assignments", payload, headers)

    def list_aircraft_assignments(self, headers, params=None):
        return self._request("GET", "/charter/aircraft-assignments", headers=headers, params=params)

    def get_aircraft_assignment(self, assignment_id, headers):
        return self._request("GET", f"/charter/aircraft-assignments/{assignment_id}", headers=headers)

    def confirm_aircraft_assignment(self, assignment_id, headers):
        return self._request("POST", f"/charter/aircraft-assignments/{assignment_id}/confirm", headers=headers)

    def release_aircraft_assignment(self, assignment_id, headers):
        return self._request("POST", f"/charter/aircraft-assignments/{assignment_id}/release", headers=headers)

    # --- Crew assignments ---
    def create_crew_assignment(self, payload, headers):
        return self._request("POST", "/charter/crew-assignments", payload, headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/charter/crew-assignments", headers=headers, params=params)

    def get_crew_assignment(self, crew_assignment_id, headers):
        return self._request("GET", f"/charter/crew-assignments/{crew_assignment_id}", headers=headers)

    def vet_crew_assignment(self, crew_assignment_id, headers):
        return self._request("POST", f"/charter/crew-assignments/{crew_assignment_id}/vet", headers=headers)

    # --- Maintenance windows ---
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", "/charter/maintenance-windows", payload, headers)

    def list_maintenance_windows(self, aircraft_id, headers, params=None):
        return self._request("GET", f"/charter/aircraft/{aircraft_id}/maintenance-windows", headers=headers, params=params)

    def get_maintenance_window(self, window_id, headers):
        return self._request("GET", f"/charter/maintenance-windows/{window_id}", headers=headers)

    def complete_maintenance_window(self, window_id, headers):
        return self._request("POST", f"/charter/maintenance-windows/{window_id}/complete", headers=headers)

    def cancel_maintenance_window(self, window_id, headers):
        return self._request("POST", f"/charter/maintenance-windows/{window_id}/cancel", headers=headers)

    # --- Passengers ---
    def create_passenger(self, payload, headers):
        return self._request("POST", "/charter/passengers", payload, headers)

    def list_passengers(self, trip_id, headers, params=None):
        return self._request("GET", f"/charter/trip-requests/{trip_id}/passengers", headers=headers, params=params)

    def get_passenger(self, passenger_id, headers):
        return self._request("GET", f"/charter/passengers/{passenger_id}", headers=headers)

    def screen_passenger(self, passenger_id, payload, headers):
        return self._request("POST", f"/charter/passengers/{passenger_id}/screen", payload, headers)

    # --- Overflight permits ---
    def create_overflight_permit(self, payload, headers):
        return self._request("POST", "/charter/overflight-permits", payload, headers)

    def list_overflight_permits(self, trip_id, headers, params=None):
        return self._request("GET", f"/charter/trip-requests/{trip_id}/overflight-permits", headers=headers, params=params)

    def get_overflight_permit(self, permit_id, headers):
        return self._request("GET", f"/charter/overflight-permits/{permit_id}", headers=headers)

    def decide_overflight_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/charter/overflight-permits/{permit_id}/decide", payload, headers)

    # --- Payments ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/charter/payments", payload, headers)

    def list_payments(self, trip_id, headers, params=None):
        return self._request("GET", f"/charter/trip-requests/{trip_id}/payments", headers=headers, params=params)

    # --- Flight logs ---
    def create_flight_log(self, payload, headers):
        return self._request("POST", "/charter/flight-logs", payload, headers)

    def list_flight_logs(self, headers, params=None):
        return self._request("GET", "/charter/flight-logs", headers=headers, params=params)

    def get_flight_log(self, flight_log_id, headers):
        return self._request("GET", f"/charter/flight-logs/{flight_log_id}", headers=headers)

    # --- Owner statements ---
    def list_owner_statements(self, owner_id, headers, params=None):
        return self._request("GET", f"/charter/aircraft-owners/{owner_id}/owner-statements", headers=headers, params=params)

    def list_trip_owner_statements(self, trip_id, headers, params=None):
        return self._request("GET", f"/charter/trip-requests/{trip_id}/owner-statements", headers=headers, params=params)

    def issue_owner_statement(self, statement_id, headers):
        return self._request("POST", f"/charter/owner-statements/{statement_id}/issue", headers=headers)

    # --- Compliance findings ---
    def create_compliance_finding(self, payload, headers):
        return self._request("POST", "/charter/compliance-findings", payload, headers)

    def list_compliance_findings(self, headers, params=None):
        return self._request("GET", "/charter/compliance-findings", headers=headers, params=params)

    def get_compliance_finding(self, finding_id, headers):
        return self._request("GET", f"/charter/compliance-findings/{finding_id}", headers=headers)

    def resolve_compliance_finding(self, finding_id, headers):
        return self._request("POST", f"/charter/compliance-findings/{finding_id}/resolve", headers=headers)

    # --- Weather advisories ---
    def create_weather_advisory(self, payload, headers):
        return self._request("POST", "/charter/weather-advisories", payload, headers)

    def list_weather_advisories(self, headers, params=None):
        return self._request("GET", "/charter/weather-advisories", headers=headers, params=params)


api_client = ApiClient()
