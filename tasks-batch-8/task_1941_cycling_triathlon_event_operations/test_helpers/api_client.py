"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Event ---
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def advance_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/advance", headers=headers)

    def start_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/start", headers=headers)

    def finalize_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/finalize", headers=headers)

    def cancel_event(self, event_id, headers, reason="cancelled"):
        return self._request("POST", f"/events/{event_id}/cancel",
                             {"reason": reason}, headers)

    def run_ops(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/run-ops", headers=headers)

    # --- RoadSegment / CoursePermit ---
    def create_road_segment(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/road-segments",
                             payload, headers)

    def list_road_segments(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/road-segments",
                             headers=headers, params=params)

    def get_road_segment(self, segment_id, headers):
        return self._request("GET", f"/road-segments/{segment_id}", headers=headers)

    def create_permit(self, segment_id, payload, headers):
        return self._request("POST", f"/road-segments/{segment_id}/permits",
                             payload, headers)

    def list_permits(self, segment_id, headers, params=None):
        return self._request("GET", f"/road-segments/{segment_id}/permits",
                             headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/submit", headers=headers)

    def approve_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/approve", headers=headers)

    def reject_permit(self, permit_id, headers, reason="rejected"):
        return self._request("POST", f"/permits/{permit_id}/reject",
                             {"reason": reason}, headers)

    # --- Wave ---
    def create_wave(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/waves", payload, headers)

    def list_waves(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/waves",
                             headers=headers, params=params)

    def get_wave(self, wave_id, headers):
        return self._request("GET", f"/waves/{wave_id}", headers=headers)

    def close_wave(self, wave_id, headers):
        return self._request("POST", f"/waves/{wave_id}/close", headers=headers)

    def reopen_wave(self, wave_id, headers):
        return self._request("POST", f"/waves/{wave_id}/reopen", headers=headers)

    def list_wave_registrations(self, wave_id, headers, params=None):
        return self._request("GET", f"/waves/{wave_id}/registrations",
                             headers=headers, params=params)

    # --- Athlete ---
    def create_athlete(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/athletes", payload, headers)

    def list_athletes(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/athletes",
                             headers=headers, params=params)

    def get_athlete(self, athlete_id, headers):
        return self._request("GET", f"/athletes/{athlete_id}", headers=headers)

    def update_athlete(self, athlete_id, payload, headers):
        return self._request("PATCH", f"/athletes/{athlete_id}", payload, headers)

    def list_athlete_registrations(self, athlete_id, headers, params=None):
        return self._request("GET", f"/athletes/{athlete_id}/registrations",
                             headers=headers, params=params)

    # --- Registration ---
    def create_registration(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/registrations",
                             payload, headers)

    def list_registrations(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/registrations",
                             headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/registrations/{registration_id}",
                             headers=headers)

    def pay_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/pay",
                             headers=headers)

    def confirm_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/confirm",
                             headers=headers)

    def withdraw_registration(self, registration_id, headers, payload=None):
        return self._request("POST", f"/registrations/{registration_id}/withdraw",
                             payload if payload is not None else {}, headers)

    def mark_dnf(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/mark-dnf",
                             headers=headers)

    def check_in_bike(self, registration_id, bib_code, headers):
        return self._request("POST", f"/registrations/{registration_id}/check-in-bike",
                             {"bib_code": bib_code}, headers)

    def check_out_bike(self, registration_id, bib_code, headers):
        return self._request("POST",
                             f"/registrations/{registration_id}/check-out-bike",
                             {"bib_code": bib_code}, headers)

    def list_bike_checks(self, registration_id, headers, params=None):
        return self._request("GET", f"/registrations/{registration_id}/bike-checks",
                             headers=headers, params=params)

    # --- AidStation / VolunteerAssignment ---
    def create_aid_station(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/aid-stations",
                             payload, headers)

    def list_aid_stations(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/aid-stations",
                             headers=headers, params=params)

    def get_aid_station(self, station_id, headers):
        return self._request("GET", f"/aid-stations/{station_id}", headers=headers)

    def allocate_water(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/allocate-water",
                             headers=headers)

    def deallocate_water(self, station_id, headers):
        return self._request("POST", f"/aid-stations/{station_id}/deallocate-water",
                             headers=headers)

    def create_volunteer_assignment(self, station_id, payload, headers):
        return self._request("POST", f"/aid-stations/{station_id}/assignments",
                             payload, headers)

    def list_volunteer_assignments(self, station_id, headers, params=None):
        return self._request("GET", f"/aid-stations/{station_id}/assignments",
                             headers=headers, params=params)

    def get_volunteer_assignment(self, assignment_id, headers):
        return self._request("GET", f"/volunteer-assignments/{assignment_id}",
                             headers=headers)

    def confirm_volunteer_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"/volunteer-assignments/{assignment_id}/confirm",
                             headers=headers)

    def decline_volunteer_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"/volunteer-assignments/{assignment_id}/decline",
                             headers=headers)

    def no_show_volunteer_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"/volunteer-assignments/{assignment_id}/no-show",
                             headers=headers)

    # --- SafetyAssessment ---
    def create_safety_assessment(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/safety-assessments",
                             payload, headers)

    def list_safety_assessments(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/safety-assessments",
                             headers=headers, params=params)

    def get_safety_assessment(self, assessment_id, headers):
        return self._request("GET", f"/safety-assessments/{assessment_id}",
                             headers=headers)

    # --- TimingRecord / Result ---
    def create_timing_record(self, registration_id, payload, headers):
        return self._request("POST",
                             f"/registrations/{registration_id}/timing-records",
                             payload, headers)

    def list_timing_records(self, registration_id, headers, params=None):
        return self._request("GET",
                             f"/registrations/{registration_id}/timing-records",
                             headers=headers, params=params)

    def get_timing_record(self, record_id, headers):
        return self._request("GET", f"/timing-records/{record_id}", headers=headers)

    def validate_timing_record(self, record_id, headers):
        return self._request("POST", f"/timing-records/{record_id}/validate",
                             headers=headers)

    def invalidate_timing_record(self, record_id, headers):
        return self._request("POST", f"/timing-records/{record_id}/invalidate",
                             headers=headers)

    def list_event_results(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/results",
                             headers=headers, params=params)

    def get_registration_results(self, registration_id, headers, params=None):
        return self._request("GET", f"/registrations/{registration_id}/results",
                             headers=headers, params=params)

    def get_result(self, result_id, headers):
        return self._request("GET", f"/results/{result_id}", headers=headers)

    def correct_result(self, result_id, payload, headers):
        return self._request("POST", f"/results/{result_id}/corrections",
                             payload, headers)

    # --- Penalty / Appeal ---
    def create_penalty(self, registration_id, payload, headers):
        return self._request("POST", f"/registrations/{registration_id}/penalties",
                             payload, headers)

    def list_penalties(self, registration_id, headers, params=None):
        return self._request("GET", f"/registrations/{registration_id}/penalties",
                             headers=headers, params=params)

    def get_penalty(self, penalty_id, headers):
        return self._request("GET", f"/penalties/{penalty_id}", headers=headers)

    def amend_penalty(self, penalty_id, payload, headers):
        return self._request("POST", f"/penalties/{penalty_id}/amend",
                             payload, headers)

    def create_appeal(self, penalty_id, payload, headers):
        return self._request("POST", f"/penalties/{penalty_id}/appeals",
                             payload, headers)

    def list_appeals(self, penalty_id, headers, params=None):
        return self._request("GET", f"/penalties/{penalty_id}/appeals",
                             headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def begin_review_appeal(self, appeal_id, headers):
        return self._request("POST", f"/appeals/{appeal_id}/begin-review",
                             headers=headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decide",
                             payload, headers)


api_client = ApiClient()
