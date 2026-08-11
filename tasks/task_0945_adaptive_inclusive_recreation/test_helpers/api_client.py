"""API client: one method per endpoint defined in the PRD.

Every resource is mounted under the /recreation prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/recreation"


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    # ---------------- operating periods ----------------
    def create_operating_period(self, payload, headers):
        return self._request("POST", f"{BASE}/operating-periods", payload, headers)

    def get_operating_period(self, period_id, headers):
        return self._request("GET", f"{BASE}/operating-periods/{period_id}", headers=headers)

    def set_period_posture(self, period_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/operating-periods/{period_id}/posture", payload, headers
        )

    # ---------------- fee scale bands ----------------
    def create_fee_scale_band(self, payload, headers):
        return self._request("POST", f"{BASE}/fee-scale-bands", payload, headers)

    def get_fee_scale_band(self, band_id, headers):
        return self._request("GET", f"{BASE}/fee-scale-bands/{band_id}", headers=headers)

    # ---------------- participants ----------------
    def create_participant(self, payload, headers):
        return self._request("POST", f"{BASE}/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", f"{BASE}/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"{BASE}/participants/{participant_id}", headers=headers)

    def patch_participant(self, participant_id, payload, headers):
        return self._request("PATCH", f"{BASE}/participants/{participant_id}", payload, headers)

    def set_participant_status(self, participant_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/participants/{participant_id}/status", payload, headers
        )

    def get_participant_eligibility(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/participants/{participant_id}/eligibility",
            headers=headers, params=params,
        )

    # ---------------- caregivers ----------------
    def create_caregiver(self, payload, headers):
        return self._request("POST", f"{BASE}/caregivers", payload, headers)

    def list_caregivers(self, headers, params=None):
        return self._request("GET", f"{BASE}/caregivers", headers=headers, params=params)

    def get_caregiver(self, caregiver_id, headers):
        return self._request("GET", f"{BASE}/caregivers/{caregiver_id}", headers=headers)

    # ---------------- support assessments ----------------
    def create_support_assessment(self, payload, headers):
        return self._request("POST", f"{BASE}/support-assessments", payload, headers)

    def list_support_assessments(self, headers, params=None):
        return self._request("GET", f"{BASE}/support-assessments", headers=headers, params=params)

    def get_support_assessment(self, assessment_id, headers):
        return self._request("GET", f"{BASE}/support-assessments/{assessment_id}", headers=headers)

    def activate_support_assessment(self, assessment_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/support-assessments/{assessment_id}/activate", payload or {}, headers
        )

    # ---------------- consents ----------------
    def create_consent(self, payload, headers):
        return self._request("POST", f"{BASE}/consents", payload, headers)

    def list_consents(self, headers, params=None):
        return self._request("GET", f"{BASE}/consents", headers=headers, params=params)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"{BASE}/consents/{consent_id}", headers=headers)

    def sign_consent(self, consent_id, payload, headers):
        return self._request("POST", f"{BASE}/consents/{consent_id}/sign", payload, headers)

    def revoke_consent(self, consent_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/consents/{consent_id}/revoke", payload or {}, headers
        )

    # ---------------- activity programs ----------------
    def create_activity_program(self, payload, headers):
        return self._request("POST", f"{BASE}/activity-programs", payload, headers)

    def get_activity_program(self, program_id, headers):
        return self._request("GET", f"{BASE}/activity-programs/{program_id}", headers=headers)

    # ---------------- program sessions ----------------
    def create_program_session(self, payload, headers):
        return self._request("POST", f"{BASE}/program-sessions", payload, headers)

    def list_program_sessions(self, headers, params=None):
        return self._request("GET", f"{BASE}/program-sessions", headers=headers, params=params)

    def get_program_session(self, session_id, headers):
        return self._request("GET", f"{BASE}/program-sessions/{session_id}", headers=headers)

    def get_staffing_summary(self, session_id, headers):
        return self._request(
            "GET", f"{BASE}/program-sessions/{session_id}/staffing-summary", headers=headers
        )

    def open_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/program-sessions/{session_id}/open", payload or {}, headers
        )

    def lock_staffing(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/program-sessions/{session_id}/lock-staffing", payload or {}, headers
        )

    def unlock_staffing(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/program-sessions/{session_id}/unlock-staffing", payload or {}, headers
        )

    def deliver_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/program-sessions/{session_id}/deliver", payload or {}, headers
        )

    def cancel_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/program-sessions/{session_id}/cancel", payload or {}, headers
        )

    # ---------------- enrollments ----------------
    def create_enrollment(self, payload, headers):
        return self._request("POST", f"{BASE}/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", f"{BASE}/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"{BASE}/enrollments/{enrollment_id}", headers=headers)

    def confirm_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/enrollments/{enrollment_id}/confirm", payload or {}, headers
        )

    def withdraw_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/enrollments/{enrollment_id}/withdraw", payload or {}, headers
        )

    def record_attendance(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/enrollments/{enrollment_id}/attendance", payload, headers
        )

    # ---------------- enrollment charges ----------------
    def list_enrollment_charges(self, headers, params=None):
        return self._request("GET", f"{BASE}/enrollment-charges", headers=headers, params=params)

    def get_enrollment_charge(self, charge_id, headers):
        return self._request("GET", f"{BASE}/enrollment-charges/{charge_id}", headers=headers)

    def record_payment(self, charge_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/enrollment-charges/{charge_id}/payments", payload, headers
        )

    # ---------------- staff ----------------
    def create_staff_member(self, payload, headers):
        return self._request("POST", f"{BASE}/staff-members", payload, headers)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"{BASE}/staff-members/{staff_id}", headers=headers)

    def create_staff_certification(self, payload, headers):
        return self._request("POST", f"{BASE}/staff-certifications", payload, headers)

    def list_staff_certifications(self, headers, params=None):
        return self._request("GET", f"{BASE}/staff-certifications", headers=headers, params=params)

    def get_staff_certification(self, certification_id, headers):
        return self._request(
            "GET", f"{BASE}/staff-certifications/{certification_id}", headers=headers
        )

    def renew_certification(self, certification_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/staff-certifications/{certification_id}/renew", payload, headers
        )

    def create_staff_assignment(self, payload, headers):
        return self._request("POST", f"{BASE}/staff-assignments", payload, headers)

    def list_staff_assignments(self, headers, params=None):
        return self._request("GET", f"{BASE}/staff-assignments", headers=headers, params=params)

    def get_staff_assignment(self, assignment_id, headers):
        return self._request("GET", f"{BASE}/staff-assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/staff-assignments/{assignment_id}/confirm", payload or {}, headers
        )

    def withdraw_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/staff-assignments/{assignment_id}/withdraw", payload or {}, headers
        )

    def revalidate_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/staff-assignments/{assignment_id}/revalidate", payload or {}, headers
        )

    # ---------------- equipment ----------------
    def create_equipment_item(self, payload, headers):
        return self._request("POST", f"{BASE}/equipment-items", payload, headers)

    def get_equipment_item(self, item_id, headers):
        return self._request("GET", f"{BASE}/equipment-items/{item_id}", headers=headers)

    def record_inspection(self, item_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/equipment-items/{item_id}/inspections", payload, headers
        )

    def create_equipment_reservation(self, payload, headers):
        return self._request("POST", f"{BASE}/equipment-reservations", payload, headers)

    def list_equipment_reservations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/equipment-reservations", headers=headers, params=params
        )

    def get_equipment_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"{BASE}/equipment-reservations/{reservation_id}", headers=headers
        )

    def check_out_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/equipment-reservations/{reservation_id}/check-out",
            payload or {}, headers,
        )

    def return_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/equipment-reservations/{reservation_id}/return", payload, headers
        )

    def release_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/equipment-reservations/{reservation_id}/release",
            payload or {}, headers,
        )

    # ---------------- transport ----------------
    def create_transport_run(self, payload, headers):
        return self._request("POST", f"{BASE}/transport-runs", payload, headers)

    def list_transport_runs(self, headers, params=None):
        return self._request("GET", f"{BASE}/transport-runs", headers=headers, params=params)

    def get_transport_run(self, run_id, headers):
        return self._request("GET", f"{BASE}/transport-runs/{run_id}", headers=headers)

    def create_transport_booking(self, payload, headers):
        return self._request("POST", f"{BASE}/transport-bookings", payload, headers)

    def list_transport_bookings(self, headers, params=None):
        return self._request("GET", f"{BASE}/transport-bookings", headers=headers, params=params)

    def get_transport_booking(self, booking_id, headers):
        return self._request("GET", f"{BASE}/transport-bookings/{booking_id}", headers=headers)

    def confirm_transport_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/transport-bookings/{booking_id}/confirm", payload or {}, headers
        )

    def cancel_transport_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/transport-bookings/{booking_id}/cancel", payload or {}, headers
        )

    # ---------------- funding ----------------
    def create_funding_source(self, payload, headers):
        return self._request("POST", f"{BASE}/funding-sources", payload, headers)

    def list_funding_sources(self, headers, params=None):
        return self._request("GET", f"{BASE}/funding-sources", headers=headers, params=params)

    def get_funding_source(self, source_id, headers):
        return self._request("GET", f"{BASE}/funding-sources/{source_id}", headers=headers)

    def close_funding_source(self, source_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/funding-sources/{source_id}/close", payload or {}, headers
        )

    def get_funding_selection(self, headers, params=None):
        return self._request("GET", f"{BASE}/funding-selection", headers=headers, params=params)

    def create_scholarship_award(self, payload, headers):
        return self._request("POST", f"{BASE}/scholarship-awards", payload, headers)

    def list_scholarship_awards(self, headers, params=None):
        return self._request("GET", f"{BASE}/scholarship-awards", headers=headers, params=params)

    def get_scholarship_award(self, award_id, headers):
        return self._request("GET", f"{BASE}/scholarship-awards/{award_id}", headers=headers)

    def encumber_award(self, award_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/scholarship-awards/{award_id}/encumber", payload or {}, headers
        )

    def disburse_award(self, award_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/scholarship-awards/{award_id}/disburse", payload, headers
        )

    def release_award(self, award_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/scholarship-awards/{award_id}/release", payload or {}, headers
        )

    # ---------------- goals ----------------
    def create_goal(self, payload, headers):
        return self._request("POST", f"{BASE}/goals", payload, headers)

    def list_goals(self, headers, params=None):
        return self._request("GET", f"{BASE}/goals", headers=headers, params=params)

    def get_goal(self, goal_id, headers):
        return self._request("GET", f"{BASE}/goals/{goal_id}", headers=headers)

    def create_goal_rating(self, goal_id, payload, headers):
        return self._request("POST", f"{BASE}/goals/{goal_id}/ratings", payload, headers)

    def list_goal_ratings(self, headers, params=None):
        return self._request("GET", f"{BASE}/goal-ratings", headers=headers, params=params)

    def get_goal_rating(self, rating_id, headers):
        return self._request("GET", f"{BASE}/goal-ratings/{rating_id}", headers=headers)


api_client = ApiClient()
