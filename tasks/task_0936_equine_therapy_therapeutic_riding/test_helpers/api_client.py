"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Logical clock ----------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------- Condition policies ----------
    def create_condition_policy(self, payload, headers):
        return self._request("POST", "/condition-policies", payload, headers)

    def list_condition_policies(self, headers, params=None):
        return self._request("GET", "/condition-policies", headers=headers, params=params)

    # ---------- Riders ----------
    def create_rider(self, payload, headers):
        return self._request("POST", "/riders", payload, headers)

    def get_rider(self, rider_id, headers):
        return self._request("GET", f"/riders/{rider_id}", headers=headers)

    def list_riders(self, headers, params=None):
        return self._request("GET", "/riders", headers=headers, params=params)

    def update_rider(self, rider_id, payload, headers):
        return self._request("PATCH", f"/riders/{rider_id}", payload, headers)

    def activate_rider(self, rider_id, headers):
        return self._request("POST", f"/riders/{rider_id}/activate", {}, headers)

    def withdraw_rider(self, rider_id, payload, headers):
        return self._request("POST", f"/riders/{rider_id}/withdraw", payload, headers)

    def grant_medical_clearance(self, rider_id, payload, headers):
        return self._request(
            "POST", f"/riders/{rider_id}/medical-clearance", payload, headers
        )

    # ---------- Medical releases ----------
    def create_medical_release(self, rider_id, payload, headers):
        return self._request(
            "POST", f"/riders/{rider_id}/medical-releases", payload, headers
        )

    def list_medical_releases(self, headers, params=None):
        return self._request("GET", "/medical-releases", headers=headers, params=params)

    def get_medical_release(self, release_id, headers):
        return self._request("GET", f"/medical-releases/{release_id}", headers=headers)

    def revoke_medical_release(self, release_id, payload, headers):
        return self._request(
            "POST", f"/medical-releases/{release_id}/revoke", payload, headers
        )

    # ---------- Assessments ----------
    def create_assessment(self, rider_id, payload, headers):
        return self._request("POST", f"/riders/{rider_id}/assessments", payload, headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    # ---------- Horses ----------
    def create_horse(self, payload, headers):
        return self._request("POST", "/horses", payload, headers)

    def get_horse(self, horse_id, headers):
        return self._request("GET", f"/horses/{horse_id}", headers=headers)

    def hold_horse(self, horse_id, payload, headers):
        return self._request("POST", f"/horses/{horse_id}/hold", payload, headers)

    def release_horse_hold(self, horse_id, headers):
        return self._request("POST", f"/horses/{horse_id}/release-hold", {}, headers)

    def get_horse_workload(self, horse_id, headers, params=None):
        return self._request(
            "GET", f"/horses/{horse_id}/workload", headers=headers, params=params
        )

    # ---------- Volunteers ----------
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def create_qualification(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/qualifications", payload, headers
        )

    def list_qualifications(self, headers, params=None):
        return self._request(
            "GET", "/volunteer-qualifications", headers=headers, params=params
        )

    def get_qualification(self, qualification_id, headers):
        return self._request(
            "GET", f"/volunteer-qualifications/{qualification_id}", headers=headers
        )

    def sign_off_qualification(self, qualification_id, payload, headers):
        return self._request(
            "POST",
            f"/volunteer-qualifications/{qualification_id}/sign-off",
            payload,
            headers,
        )

    def record_retraining(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/retraining", payload, headers
        )

    def get_service_hours(self, volunteer_id, headers, params=None):
        return self._request(
            "GET", f"/volunteers/{volunteer_id}/service-hours", headers=headers, params=params
        )

    # ---------- Instructors ----------
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    def list_instructors(self, headers, params=None):
        return self._request("GET", "/instructors", headers=headers, params=params)

    def accrue_ce_hours(self, instructor_id, payload, headers):
        return self._request(
            "POST", f"/instructors/{instructor_id}/ce-hours", payload, headers
        )

    def renew_certification(self, instructor_id, payload, headers):
        return self._request(
            "POST", f"/instructors/{instructor_id}/renew-certification", payload, headers
        )

    # ---------- Sessions ----------
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def get_session_eligibility(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/sessions/{session_id}/eligibility", headers=headers, params=params
        )

    def confirm_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/confirm", {}, headers)

    def complete_session(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/complete", payload, headers)

    def cancel_session(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", payload, headers)

    def record_no_show(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/no-show", {}, headers)

    # ---------- Crew assignments ----------
    def create_crew_assignment(self, session_id, payload, headers):
        return self._request(
            "POST", f"/sessions/{session_id}/crew-assignments", payload, headers
        )

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/crew-assignments", headers=headers, params=params)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"/crew-assignments/{assignment_id}", headers=headers)

    def release_crew_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/crew-assignments/{assignment_id}/release", payload, headers
        )

    # ---------- Goals ----------
    def create_goal(self, rider_id, payload, headers):
        return self._request("POST", f"/riders/{rider_id}/goals", payload, headers)

    def list_goals(self, headers, params=None):
        return self._request("GET", "/goals", headers=headers, params=params)

    def get_goal(self, goal_id, headers):
        return self._request("GET", f"/goals/{goal_id}", headers=headers)

    def discontinue_goal(self, goal_id, payload, headers):
        return self._request("POST", f"/goals/{goal_id}/discontinue", payload, headers)

    def reopen_goal(self, goal_id, payload, headers):
        return self._request("POST", f"/goals/{goal_id}/reopen", payload, headers)

    def run_goal_staleness_sweep(self, headers):
        return self._request("POST", "/_ops/goal-staleness-sweep", {}, headers)

    # ---------- Progress notes ----------
    def create_progress_note(self, session_id, payload, headers):
        return self._request(
            "POST", f"/sessions/{session_id}/progress-notes", payload, headers
        )

    def list_progress_notes(self, headers, params=None):
        return self._request("GET", "/progress-notes", headers=headers, params=params)

    def get_progress_note(self, note_id, headers):
        return self._request("GET", f"/progress-notes/{note_id}", headers=headers)

    def finalize_progress_note(self, note_id, headers):
        return self._request("POST", f"/progress-notes/{note_id}/finalize", {}, headers)

    # ---------- Grants and scholarship awards ----------
    def create_grant(self, payload, headers):
        return self._request("POST", "/grants", payload, headers)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    def create_scholarship_award(self, rider_id, payload, headers):
        return self._request(
            "POST", f"/riders/{rider_id}/scholarship-awards", payload, headers
        )

    def list_scholarship_awards(self, headers, params=None):
        return self._request(
            "GET", "/scholarship-awards", headers=headers, params=params
        )

    def get_scholarship_award(self, award_id, headers):
        return self._request("GET", f"/scholarship-awards/{award_id}", headers=headers)

    # ---------- Charges and funding allocations ----------
    def list_charges(self, headers, params=None):
        return self._request("GET", "/charges", headers=headers, params=params)

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/charges/{charge_id}", headers=headers)

    def reverse_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/charges/{charge_id}/reverse", payload, headers)

    def list_funding_allocations(self, headers, params=None):
        return self._request(
            "GET", "/funding-allocations", headers=headers, params=params
        )

    def get_funding_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/funding-allocations/{allocation_id}", headers=headers
        )

    # ---------- Incidents ----------
    def create_incident(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def review_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/review", payload, headers)

    def close_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/close", payload, headers)

    # ---------- Period reports ----------
    def create_period_report(self, payload, headers):
        return self._request("POST", "/period-reports", payload, headers)

    def get_period_report(self, report_id, headers):
        return self._request("GET", f"/period-reports/{report_id}", headers=headers)

    def finalize_period_report(self, report_id, headers):
        return self._request(
            "POST", f"/period-reports/{report_id}/finalize", {}, headers
        )


api_client = ApiClient()
