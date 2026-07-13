"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Tunnels ----
    def create_tunnel(self, payload, headers):
        return self._request("POST", "/tunnels", payload, headers)

    def get_tunnel(self, tunnel_id, headers):
        return self._request("GET", f"/tunnels/{tunnel_id}", headers=headers)

    def tunnel_maintenance(self, tunnel_id, payload, headers):
        return self._request("POST", f"/tunnels/{tunnel_id}/maintenance", payload, headers)

    # ---- Instructors ----
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    # ---- Members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def get_member_statement(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}/statement", headers=headers)

    # ---- Waivers ----
    def create_waiver(self, payload, headers):
        return self._request("POST", "/waivers", payload, headers)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/waivers/{waiver_id}", headers=headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/waivers", headers=headers, params=params)

    # ---- Memberships ----
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/cancel", {}, headers)

    # ---- Packages ----
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    # ---- Bookings ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    # ---- Sessions ----
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def assign_instructor(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/assign-instructor", payload, headers)

    def start_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/start", {}, headers)

    def close_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/close", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", {}, headers)

    # ---- Flights ----
    def create_flight(self, payload, headers):
        return self._request("POST", "/flights", payload, headers)

    def get_flight(self, flight_id, headers):
        return self._request("GET", f"/flights/{flight_id}", headers=headers)

    def list_flights(self, headers, params=None):
        return self._request("GET", "/flights", headers=headers, params=params)

    def check_in_flight(self, flight_id, headers):
        return self._request("POST", f"/flights/{flight_id}/check-in", {}, headers)

    def complete_flight(self, flight_id, headers):
        return self._request("POST", f"/flights/{flight_id}/complete", {}, headers)

    def abort_flight(self, flight_id, payload, headers):
        return self._request("POST", f"/flights/{flight_id}/abort", payload, headers)

    def no_show_flight(self, flight_id, headers):
        return self._request("POST", f"/flights/{flight_id}/no-show", {}, headers)

    def cancel_flight(self, flight_id, headers):
        return self._request("POST", f"/flights/{flight_id}/cancel", {}, headers)

    def purchase_video(self, flight_id, headers):
        return self._request("POST", f"/flights/{flight_id}/video", {}, headers)

    # ---- Coaching ----
    def create_coaching(self, payload, headers):
        return self._request("POST", "/coaching-bookings", payload, headers)

    def get_coaching(self, coaching_id, headers):
        return self._request("GET", f"/coaching-bookings/{coaching_id}", headers=headers)

    def list_coaching(self, headers, params=None):
        return self._request("GET", "/coaching-bookings", headers=headers, params=params)

    # ---- Logical clock (test-driving capability) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
