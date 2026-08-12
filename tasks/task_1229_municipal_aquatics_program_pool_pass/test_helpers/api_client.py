"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- facility ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/facilities", headers=headers, params=params)

    def list_facility_chemistry_logs(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/facilities/{facility_id}/chemistry-logs",
            headers=headers, params=params,
        )

    def list_facility_closures(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/facilities/{facility_id}/closures",
            headers=headers, params=params,
        )

    def create_chemistry_log(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/chemistry-logs", payload, headers
        )

    def create_closure(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/closures", payload, headers
        )

    def reopen_facility(self, facility_id, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/reopen", {}, headers
        )

    # --- season ---
    def create_season(self, payload, headers):
        return self._request("POST", "/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/seasons", headers=headers, params=params)

    def list_season_passes(self, season_id, headers):
        return self._request("GET", f"/seasons/{season_id}/passes", headers=headers)

    def publish_season(self, season_id, headers):
        return self._request("POST", f"/seasons/{season_id}/publish", {}, headers)

    def close_season(self, season_id, headers):
        return self._request("POST", f"/seasons/{season_id}/close", {}, headers)

    # --- pass holder ---
    def create_pass_holder(self, payload, headers):
        return self._request("POST", "/pass-holders", payload, headers)

    def get_pass_holder(self, holder_id, headers):
        return self._request("GET", f"/pass-holders/{holder_id}", headers=headers)

    def list_pass_holder_passes(self, holder_id, headers):
        return self._request(
            "GET", f"/pass-holders/{holder_id}/passes", headers=headers
        )

    def list_pass_holder_admissions(self, holder_id, headers):
        return self._request(
            "GET", f"/pass-holders/{holder_id}/admissions", headers=headers
        )

    def list_pass_holder_rentals(self, holder_id, headers):
        return self._request(
            "GET", f"/pass-holders/{holder_id}/rentals", headers=headers
        )

    def list_pass_holder_enrollments(self, holder_id, headers):
        return self._request(
            "GET", f"/pass-holders/{holder_id}/enrollments", headers=headers
        )

    # --- season pass ---
    def create_pass(self, payload, headers):
        return self._request("POST", "/passes", payload, headers)

    def get_pass(self, pass_id, headers):
        return self._request("GET", f"/passes/{pass_id}", headers=headers)

    def refund_pass(self, pass_id, headers):
        return self._request("POST", f"/passes/{pass_id}/refund", {}, headers)

    def list_pass_admissions(self, pass_id, headers):
        return self._request("GET", f"/passes/{pass_id}/admissions", headers=headers)

    # --- daily admission ---
    def create_admission(self, payload, headers):
        return self._request("POST", "/admissions", payload, headers)

    def get_admission(self, admission_id, headers):
        return self._request("GET", f"/admissions/{admission_id}", headers=headers)

    def list_admissions(self, headers, params=None):
        return self._request("GET", "/admissions", headers=headers, params=params)

    def enter_admission(self, admission_id, headers):
        return self._request(
            "POST", f"/admissions/{admission_id}/enter", {}, headers
        )

    def exit_admission(self, admission_id, headers):
        return self._request("POST", f"/admissions/{admission_id}/exit", {}, headers)

    # --- lesson level ---
    def create_lesson_level(self, payload, headers):
        return self._request("POST", "/lesson-levels", payload, headers)

    def get_lesson_level(self, level_id, headers):
        return self._request("GET", f"/lesson-levels/{level_id}", headers=headers)

    def list_lesson_levels(self, headers, params=None):
        return self._request("GET", "/lesson-levels", headers=headers, params=params)

    def list_level_enrollments_as_evidence(self, level_id, headers):
        return self._request(
            "GET", f"/lesson-levels/{level_id}/enrollments-as-evidence",
            headers=headers,
        )

    # --- lesson session ---
    def create_lesson_session(self, payload, headers):
        return self._request("POST", "/lesson-sessions", payload, headers)

    def get_lesson_session(self, session_id, headers):
        return self._request(
            "GET", f"/lesson-sessions/{session_id}", headers=headers
        )

    def list_lesson_sessions(self, headers, params=None):
        return self._request(
            "GET", "/lesson-sessions", headers=headers, params=params
        )

    def list_session_enrollments(self, session_id, headers):
        return self._request(
            "GET", f"/lesson-sessions/{session_id}/enrollments", headers=headers
        )

    def list_session_lane_allocations(self, session_id, headers):
        return self._request(
            "GET", f"/lesson-sessions/{session_id}/lane-allocations", headers=headers
        )

    def schedule_lesson_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/lesson-sessions/{session_id}/schedule", payload, headers
        )

    def cancel_lesson_session(self, session_id, headers):
        return self._request(
            "POST", f"/lesson-sessions/{session_id}/cancel", {}, headers
        )

    # --- enrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def drop_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/drop", {}, headers
        )

    # --- lifeguard ---
    def create_lifeguard(self, payload, headers):
        return self._request("POST", "/lifeguards", payload, headers)

    def get_lifeguard(self, lifeguard_id, headers):
        return self._request("GET", f"/lifeguards/{lifeguard_id}", headers=headers)

    def list_lifeguards(self, headers, params=None):
        return self._request("GET", "/lifeguards", headers=headers, params=params)

    def list_lifeguard_shifts(self, lifeguard_id, headers):
        return self._request(
            "GET", f"/lifeguards/{lifeguard_id}/shifts", headers=headers
        )

    def suspend_lifeguard(self, lifeguard_id, payload, headers):
        return self._request(
            "POST", f"/lifeguards/{lifeguard_id}/suspend", payload, headers
        )

    def reinstate_lifeguard(self, lifeguard_id, headers):
        return self._request(
            "POST", f"/lifeguards/{lifeguard_id}/reinstate", {}, headers
        )

    def list_lifeguard_chemistry_logs(self, lifeguard_id, headers):
        return self._request(
            "GET", f"/lifeguards/{lifeguard_id}/chemistry-logs", headers=headers
        )

    def list_lifeguard_incident_reports(self, lifeguard_id, headers):
        return self._request(
            "GET", f"/lifeguards/{lifeguard_id}/incident-reports", headers=headers
        )

    # --- shift ---
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def check_in_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/check-in", {}, headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/cancel", {}, headers)

    # --- lane allocation ---
    def create_lane_allocation(self, payload, headers):
        return self._request("POST", "/lane-allocations", payload, headers)

    def get_lane_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/lane-allocations/{allocation_id}", headers=headers
        )

    def list_lane_allocations(self, headers, params=None):
        return self._request(
            "GET", "/lane-allocations", headers=headers, params=params
        )

    def release_lane_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/lane-allocations/{allocation_id}/release", {}, headers
        )

    # --- rental ---
    def create_rental(self, payload, headers):
        return self._request("POST", "/rentals", payload, headers)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/rentals/{rental_id}", headers=headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/rentals", headers=headers, params=params)

    def approve_rental(self, rental_id, payload, headers):
        return self._request(
            "POST", f"/rentals/{rental_id}/approve", payload, headers
        )

    def reject_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/reject", {}, headers)

    def check_in_rental(self, rental_id, headers):
        return self._request(
            "POST", f"/rentals/{rental_id}/check-in", {}, headers
        )

    def check_out_rental(self, rental_id, headers):
        return self._request(
            "POST", f"/rentals/{rental_id}/check-out", {}, headers
        )

    def cancel_rental(self, rental_id, headers):
        return self._request("POST", f"/rentals/{rental_id}/cancel", {}, headers)

    # --- incident report ---
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/incident-reports", payload, headers)

    def get_incident_report(self, report_id, headers):
        return self._request(
            "GET", f"/incident-reports/{report_id}", headers=headers
        )

    def list_incident_reports(self, headers, params=None):
        return self._request(
            "GET", "/incident-reports", headers=headers, params=params
        )

    def submit_incident_report(self, report_id, headers):
        return self._request(
            "POST", f"/incident-reports/{report_id}/submit", {}, headers
        )

    def confirm_incident_report(self, report_id, headers):
        return self._request(
            "POST", f"/incident-reports/{report_id}/confirm", {}, headers
        )

    def dismiss_incident_report(self, report_id, headers):
        return self._request(
            "POST", f"/incident-reports/{report_id}/dismiss", {}, headers
        )

    # --- closure ---
    def get_closure(self, closure_id, headers):
        return self._request("GET", f"/closures/{closure_id}", headers=headers)

    def resolve_closure(self, closure_id, headers):
        return self._request("POST", f"/closures/{closure_id}/resolve", {}, headers)


api_client = ApiClient()
