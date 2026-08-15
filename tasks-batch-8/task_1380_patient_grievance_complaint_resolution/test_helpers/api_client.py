"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- HospitalUnit ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/api/hospital-units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/api/hospital-units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/api/hospital-units/{unit_id}", headers=headers)

    def patch_unit(self, unit_id, payload, headers):
        return self._request("PATCH", f"/api/hospital-units/{unit_id}", payload, headers)

    # --- StaffMember ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/api/staff-members", payload, headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/api/staff-members", headers=headers, params=params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/api/staff-members/{staff_id}", headers=headers)

    def patch_staff(self, staff_id, payload, headers):
        return self._request("PATCH", f"/api/staff-members/{staff_id}", payload, headers)

    # --- HolidayObservance ---
    def create_holiday(self, payload, headers):
        return self._request("POST", "/api/holiday-observances", payload, headers)

    def list_holidays(self, headers, params=None):
        return self._request("GET", "/api/holiday-observances", headers=headers, params=params)

    def delete_holiday(self, holiday_id, headers):
        return self._request("DELETE", f"/api/holiday-observances/{holiday_id}", headers=headers)

    # --- PatientCase ---
    def create_case(self, payload, headers):
        return self._request("POST", "/api/patient-cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/api/patient-cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/api/patient-cases/{case_id}", headers=headers)

    def get_case_timeline(self, case_id, headers):
        return self._request("GET", f"/api/patient-cases/{case_id}/timeline", headers=headers)

    def acknowledge_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/api/patient-cases/{case_id}/acknowledge",
                             payload or {}, headers)

    def withdraw_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/patient-cases/{case_id}/withdraw", payload, headers)

    def reopen_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/patient-cases/{case_id}/reopen", payload, headers)

    def fast_track_case(self, case_id, headers):
        return self._request("POST", f"/api/patient-cases/{case_id}/fast-track", {}, headers)

    def close_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/patient-cases/{case_id}/close", payload, headers)

    # --- ClassificationDecision ---
    def create_classification_decision(self, case_id, payload, headers):
        return self._request("POST", f"/api/patient-cases/{case_id}/classification-decisions",
                             payload, headers)

    def list_classification_decisions(self, headers, params=None):
        return self._request("GET", "/api/classification-decisions",
                             headers=headers, params=params)

    def get_classification_decision(self, decision_id, headers):
        return self._request("GET", f"/api/classification-decisions/{decision_id}",
                             headers=headers)

    # --- CaseAssignment ---
    def create_assignment(self, case_id, payload, headers):
        return self._request("POST", f"/api/patient-cases/{case_id}/assignments",
                             payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/api/case-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/case-assignments/{assignment_id}", headers=headers)

    def release_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/api/case-assignments/{assignment_id}/release",
                             payload, headers)

    # --- Investigation / InvestigationNote ---
    def create_investigation(self, case_id, headers):
        return self._request("POST", f"/api/patient-cases/{case_id}/investigations", {}, headers)

    def list_investigations(self, headers, params=None):
        return self._request("GET", "/api/investigations", headers=headers, params=params)

    def get_investigation(self, investigation_id, headers):
        return self._request("GET", f"/api/investigations/{investigation_id}", headers=headers)

    def create_note(self, investigation_id, payload, headers):
        return self._request("POST", f"/api/investigations/{investigation_id}/notes",
                             payload, headers)

    def submit_findings(self, investigation_id, payload, headers):
        return self._request("POST", f"/api/investigations/{investigation_id}/submit-findings",
                             payload, headers)

    def accept_findings(self, investigation_id, headers):
        return self._request("POST", f"/api/investigations/{investigation_id}/accept-findings",
                             {}, headers)

    def return_findings(self, investigation_id, payload, headers):
        return self._request("POST", f"/api/investigations/{investigation_id}/return-findings",
                             payload, headers)

    def resume_investigation(self, investigation_id, headers):
        return self._request("POST", f"/api/investigations/{investigation_id}/resume",
                             {}, headers)

    def list_notes(self, headers, params=None):
        return self._request("GET", "/api/investigation-notes", headers=headers, params=params)

    def get_note(self, note_id, headers):
        return self._request("GET", f"/api/investigation-notes/{note_id}", headers=headers)

    # --- ResponseLetter ---
    def create_letter(self, case_id, payload, headers):
        return self._request("POST", f"/api/patient-cases/{case_id}/response-letters",
                             payload, headers)

    def list_letters(self, headers, params=None):
        return self._request("GET", "/api/response-letters", headers=headers, params=params)

    def get_letter(self, letter_id, headers):
        return self._request("GET", f"/api/response-letters/{letter_id}", headers=headers)

    def submit_letter_review(self, letter_id, headers):
        return self._request("POST", f"/api/response-letters/{letter_id}/submit-review",
                             {}, headers)

    def approve_letter(self, letter_id, headers):
        return self._request("POST", f"/api/response-letters/{letter_id}/approve", {}, headers)

    def return_letter(self, letter_id, payload, headers):
        return self._request("POST", f"/api/response-letters/{letter_id}/return",
                             payload, headers)

    def issue_letter(self, letter_id, headers):
        return self._request("POST", f"/api/response-letters/{letter_id}/issue", {}, headers)

    # --- ServiceRecoveryAction ---
    def create_recovery_action(self, case_id, payload, headers):
        return self._request("POST", f"/api/patient-cases/{case_id}/recovery-actions",
                             payload, headers)

    def list_recovery_actions(self, headers, params=None):
        return self._request("GET", "/api/recovery-actions", headers=headers, params=params)

    def get_recovery_action(self, action_id, headers):
        return self._request("GET", f"/api/recovery-actions/{action_id}", headers=headers)

    def approve_recovery_action(self, action_id, headers):
        return self._request("POST", f"/api/recovery-actions/{action_id}/approve", {}, headers)

    def reject_recovery_action(self, action_id, payload, headers):
        return self._request("POST", f"/api/recovery-actions/{action_id}/reject",
                             payload, headers)

    def revoke_recovery_action(self, action_id, payload, headers):
        return self._request("POST", f"/api/recovery-actions/{action_id}/revoke",
                             payload, headers)

    # --- QualityRiskEscalation ---
    def create_escalation(self, case_id, payload, headers):
        return self._request("POST", f"/api/patient-cases/{case_id}/escalations",
                             payload, headers)

    def list_escalations(self, headers, params=None):
        return self._request("GET", "/api/escalations", headers=headers, params=params)

    def get_escalation(self, escalation_id, headers):
        return self._request("GET", f"/api/escalations/{escalation_id}", headers=headers)

    def triage_escalation(self, escalation_id, payload, headers):
        return self._request("POST", f"/api/escalations/{escalation_id}/triage",
                             payload, headers)

    def complete_escalation_review(self, escalation_id, payload, headers):
        return self._request("POST", f"/api/escalations/{escalation_id}/complete-review",
                             payload, headers)

    def adjudicate_escalation(self, escalation_id, payload, headers):
        return self._request("POST", f"/api/escalations/{escalation_id}/adjudicate",
                             payload, headers)

    # --- ReportableEvent ---
    def create_reportable_event(self, case_id, payload, headers):
        return self._request("POST", f"/api/patient-cases/{case_id}/reportable-events",
                             payload, headers)

    def list_reportable_events(self, headers, params=None):
        return self._request("GET", "/api/reportable-events", headers=headers, params=params)

    def get_reportable_event(self, event_id, headers):
        return self._request("GET", f"/api/reportable-events/{event_id}", headers=headers)

    def file_reportable_event(self, event_id, headers):
        return self._request("POST", f"/api/reportable-events/{event_id}/file", {}, headers)

    def acknowledge_reportable_event(self, event_id, payload, headers):
        return self._request("POST", f"/api/reportable-events/{event_id}/acknowledge",
                             payload, headers)

    # --- RoundingSession ---
    def create_rounding_session(self, payload, headers):
        return self._request("POST", "/api/rounding-sessions", payload, headers)

    def list_rounding_sessions(self, headers, params=None):
        return self._request("GET", "/api/rounding-sessions", headers=headers, params=params)

    def get_rounding_session(self, session_id, headers):
        return self._request("GET", f"/api/rounding-sessions/{session_id}", headers=headers)

    def complete_rounding_session(self, session_id, payload, headers):
        return self._request("POST", f"/api/rounding-sessions/{session_id}/complete",
                             payload, headers)

    def cancel_rounding_session(self, session_id, headers):
        return self._request("POST", f"/api/rounding-sessions/{session_id}/cancel", {}, headers)

    # --- InterviewRoom / InterviewBooking ---
    def create_interview_room(self, payload, headers):
        return self._request("POST", "/api/interview-rooms", payload, headers)

    def list_interview_rooms(self, headers, params=None):
        return self._request("GET", "/api/interview-rooms", headers=headers, params=params)

    def get_interview_room(self, room_id, headers):
        return self._request("GET", f"/api/interview-rooms/{room_id}", headers=headers)

    def create_interview_booking(self, payload, headers):
        return self._request("POST", "/api/interview-bookings", payload, headers)

    def list_interview_bookings(self, headers, params=None):
        return self._request("GET", "/api/interview-bookings", headers=headers, params=params)

    def get_interview_booking(self, booking_id, headers):
        return self._request("GET", f"/api/interview-bookings/{booking_id}", headers=headers)

    def cancel_interview_booking(self, booking_id, headers):
        return self._request("POST", f"/api/interview-bookings/{booking_id}/cancel", {}, headers)

    # --- SatisfactionFollowUp ---
    def list_follow_ups(self, headers, params=None):
        return self._request("GET", "/api/follow-ups", headers=headers, params=params)

    def get_follow_up(self, follow_up_id, headers):
        return self._request("GET", f"/api/follow-ups/{follow_up_id}", headers=headers)

    def respond_follow_up(self, follow_up_id, payload, headers):
        return self._request("POST", f"/api/follow-ups/{follow_up_id}/respond",
                             payload, headers)

    # --- ClockSuspension ---
    def create_clock_suspension(self, case_id, payload, headers):
        return self._request("POST", f"/api/patient-cases/{case_id}/clock-suspensions",
                             payload, headers)

    def list_clock_suspensions(self, headers, params=None):
        return self._request("GET", "/api/clock-suspensions", headers=headers, params=params)

    def get_clock_suspension(self, suspension_id, headers):
        return self._request("GET", f"/api/clock-suspensions/{suspension_id}", headers=headers)

    def close_clock_suspension(self, suspension_id, headers):
        return self._request("POST", f"/api/clock-suspensions/{suspension_id}/close",
                             {}, headers)

    # --- TrendSnapshot ---
    def compute_trend_snapshots(self, payload, headers):
        return self._request("POST", "/api/trend-snapshots/compute", payload, headers)

    def list_trend_snapshots(self, headers, params=None):
        return self._request("GET", "/api/trend-snapshots", headers=headers, params=params)

    def get_trend_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/api/trend-snapshots/{snapshot_id}", headers=headers)


api_client = ApiClient()
