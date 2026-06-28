"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient from the framework; the base _request() is inherited.
All paths are under the /v1 prefix (the logical-clock endpoint is under /_clock).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Facility ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/v1/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/v1/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/v1/facilities/{facility_id}", headers=headers)

    def run_ops(self, facility_id, headers):
        return self._request("POST", f"/v1/facilities/{facility_id}/run-ops", {}, headers)

    # --- Lane ---
    def create_lane(self, payload, headers):
        return self._request("POST", "/v1/lanes", payload, headers)

    def get_lane(self, lane_id, headers):
        return self._request("GET", f"/v1/lanes/{lane_id}", headers=headers)

    def list_lanes(self, headers, params=None):
        return self._request("GET", "/v1/lanes", headers=headers, params=params)

    # --- PitchingMachine ---
    def create_machine(self, payload, headers):
        return self._request("POST", "/v1/machines", payload, headers)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/v1/machines/{machine_id}", headers=headers)

    def list_machines(self, headers, params=None):
        return self._request("GET", "/v1/machines", headers=headers, params=params)

    # --- MaintenanceWindow ---
    def create_maintenance(self, payload, headers):
        return self._request("POST", "/v1/maintenance", payload, headers)

    def get_maintenance(self, window_id, headers):
        return self._request("GET", f"/v1/maintenance/{window_id}", headers=headers)

    def list_maintenance(self, headers, params=None):
        return self._request("GET", "/v1/maintenance", headers=headers, params=params)

    def resolve_maintenance(self, window_id, headers):
        return self._request("POST", f"/v1/maintenance/{window_id}/resolve", {}, headers)

    # --- Member ---
    def create_member(self, payload, headers):
        return self._request("POST", "/v1/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/v1/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/v1/members", headers=headers, params=params)

    def wallet_top_up(self, member_id, payload, headers):
        return self._request(
            "POST", f"/v1/members/{member_id}/wallet/top-up", payload, headers
        )

    # --- Waiver ---
    def create_waiver(self, payload, headers):
        return self._request("POST", "/v1/waivers", payload, headers)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/v1/waivers/{waiver_id}", headers=headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/v1/waivers", headers=headers, params=params)

    def void_waiver(self, waiver_id, headers):
        return self._request("POST", f"/v1/waivers/{waiver_id}/void", {}, headers)

    # --- Instructor ---
    def create_instructor(self, payload, headers):
        return self._request("POST", "/v1/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/v1/instructors/{instructor_id}", headers=headers)

    def list_instructors(self, headers, params=None):
        return self._request("GET", "/v1/instructors", headers=headers, params=params)

    # --- Booking ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/v1/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/v1/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/v1/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/v1/bookings/{booking_id}/confirm", payload, headers
        )

    def reject_booking(self, booking_id, headers):
        return self._request("POST", f"/v1/bookings/{booking_id}/reject", {}, headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/v1/bookings/{booking_id}/check-in", {}, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/v1/bookings/{booking_id}/complete", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/v1/bookings/{booking_id}/cancel", {}, headers)

    # --- Program ---
    def create_program(self, payload, headers):
        return self._request("POST", "/v1/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/v1/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/v1/programs", headers=headers, params=params)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/v1/programs/{program_id}/close", {}, headers)

    # --- Enrollment ---
    def create_enrollment(self, program_id, payload, headers):
        return self._request(
            "POST", f"/v1/programs/{program_id}/enrollments", payload, headers
        )

    def list_program_enrollments(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/v1/programs/{program_id}/enrollments", headers=headers, params=params
        )

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/v1/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/v1/enrollments", headers=headers, params=params)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/v1/enrollments/{enrollment_id}/withdraw", {}, headers
        )

    # --- Test-driving: logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
