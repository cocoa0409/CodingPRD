"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Participant ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def deactivate_participant(self, participant_id, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/deactivate", {}, headers
        )

    def get_contribution_statement(self, participant_id, headers, params=None):
        return self._request(
            "GET",
            f"/participants/{participant_id}/contribution-statement",
            headers=headers,
            params=params,
        )

    # --- GrantAward ---
    def create_grant(self, payload, headers):
        return self._request("POST", "/grant-awards", payload, headers)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grant-awards/{grant_id}", headers=headers)

    def activate_grant(self, grant_id, headers):
        return self._request(
            "POST", f"/grant-awards/{grant_id}/activate", {}, headers
        )

    def suspend_grant(self, grant_id, headers):
        return self._request(
            "POST", f"/grant-awards/{grant_id}/suspend", {}, headers
        )

    # --- Donation ---
    def create_donation(self, payload, headers):
        return self._request("POST", "/donations", payload, headers)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/donations/{donation_id}", headers=headers)

    # --- FundedService ---
    def create_funded_service(self, payload, headers):
        return self._request("POST", "/funded-services", payload, headers)

    def get_funded_service(self, fs_id, headers):
        return self._request("GET", f"/funded-services/{fs_id}", headers=headers)

    def list_funded_services(self, headers, params=None):
        return self._request(
            "GET", "/funded-services", headers=headers, params=params
        )

    def reverse_funded_service(self, fs_id, headers):
        return self._request(
            "POST", f"/funded-services/{fs_id}/reverse", {}, headers
        )

    # --- Room ---
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    # --- ActivitySession ---
    def create_session(self, payload, headers):
        return self._request("POST", "/activity-sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request(
            "GET", f"/activity-sessions/{session_id}", headers=headers
        )

    def list_sessions(self, headers, params=None):
        return self._request(
            "GET", "/activity-sessions", headers=headers, params=params
        )

    def cancel_session(self, session_id, headers):
        return self._request(
            "POST", f"/activity-sessions/{session_id}/cancel", {}, headers
        )

    # --- ActivitySignup ---
    def create_signup(self, payload, headers):
        return self._request("POST", "/activity-signups", payload, headers)

    def get_signup(self, signup_id, headers):
        return self._request(
            "GET", f"/activity-signups/{signup_id}", headers=headers
        )

    def list_signups(self, headers, params=None):
        return self._request(
            "GET", "/activity-signups", headers=headers, params=params
        )

    def cancel_signup(self, signup_id, headers):
        return self._request(
            "POST", f"/activity-signups/{signup_id}/cancel", {}, headers
        )

    # --- Vehicle ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    # --- TransportationRequest ---
    def create_transport(self, payload, headers):
        return self._request("POST", "/transportation-requests", payload, headers)

    def get_transport(self, transport_id, headers):
        return self._request(
            "GET", f"/transportation-requests/{transport_id}", headers=headers
        )

    def list_transports(self, headers, params=None):
        return self._request(
            "GET", "/transportation-requests", headers=headers, params=params
        )

    def approve_transport(self, transport_id, headers):
        return self._request(
            "POST", f"/transportation-requests/{transport_id}/approve", {}, headers
        )

    def complete_transport(self, transport_id, headers):
        return self._request(
            "POST", f"/transportation-requests/{transport_id}/complete", {}, headers
        )

    # --- MealServiceDay ---
    def create_meal_day(self, payload, headers):
        return self._request("POST", "/meal-service-days", payload, headers)

    def get_meal_day(self, day_id, headers):
        return self._request("GET", f"/meal-service-days/{day_id}", headers=headers)

    def close_meal_day(self, day_id, headers):
        return self._request(
            "POST", f"/meal-service-days/{day_id}/close", {}, headers
        )

    # --- MealReservation ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/meal-reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/meal-reservations/{reservation_id}", headers=headers
        )

    def list_reservations(self, headers, params=None):
        return self._request(
            "GET", "/meal-reservations", headers=headers, params=params
        )

    def cancel_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/meal-reservations/{reservation_id}/cancel", {}, headers
        )

    def check_in_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/meal-reservations/{reservation_id}/check-in", {}, headers
        )

    # --- WellnessProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/wellness-programs", payload, headers)

    # --- WellnessEnrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/wellness-enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/wellness-enrollments/{enrollment_id}", headers=headers
        )

    def list_enrollments(self, headers, params=None):
        return self._request(
            "GET", "/wellness-enrollments", headers=headers, params=params
        )

    def log_session(self, enrollment_id, attended, headers):
        return self._request(
            "POST",
            f"/wellness-enrollments/{enrollment_id}/log-session",
            {"attended": attended},
            headers,
        )

    def finalize_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/wellness-enrollments/{enrollment_id}/finalize", {}, headers
        )

    # --- VolunteerShift ---
    def create_volunteer_shift(self, payload, headers):
        return self._request("POST", "/volunteer-shifts", payload, headers)

    def list_volunteer_shifts(self, headers, params=None):
        return self._request(
            "GET", "/volunteer-shifts", headers=headers, params=params
        )

    # --- Reports ---
    def oaa_units_report(self, headers, params=None):
        return self._request(
            "GET", "/reports/oaa-units", headers=headers, params=params
        )


api_client = ApiClient()
