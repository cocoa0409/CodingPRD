"""API client: one method per endpoint defined in the Online Proctoring PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Institution ----
    def create_institution(self, payload, headers):
        return self._request("POST", "/institutions", payload, headers)

    def get_institution(self, institution_id, headers):
        return self._request("GET", f"/institutions/{institution_id}", headers=headers)

    # ---- Proctor ----
    def create_proctor(self, payload, headers):
        return self._request("POST", "/proctors", payload, headers)

    def get_proctor(self, proctor_id, headers):
        return self._request("GET", f"/proctors/{proctor_id}", headers=headers)

    def list_proctors(self, headers, params=None):
        return self._request("GET", "/proctors", headers=headers, params=params)

    # ---- Candidate ----
    def create_candidate(self, payload, headers):
        return self._request("POST", "/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/candidates/{candidate_id}", headers=headers)

    def list_candidates(self, headers, params=None):
        return self._request("GET", "/candidates", headers=headers, params=params)

    # ---- Exam ----
    def create_exam(self, payload, headers):
        return self._request("POST", "/exams", payload, headers)

    def get_exam(self, exam_id, headers):
        return self._request("GET", f"/exams/{exam_id}", headers=headers)

    def list_exams(self, headers, params=None):
        return self._request("GET", "/exams", headers=headers, params=params)

    def close_exam(self, exam_id, headers):
        return self._request("POST", f"/exams/{exam_id}/close", {}, headers)

    # ---- Accommodation ----
    def create_accommodation(self, payload, headers):
        return self._request("POST", "/accommodations", payload, headers)

    def get_accommodation(self, accommodation_id, headers):
        return self._request("GET", f"/accommodations/{accommodation_id}", headers=headers)

    def list_accommodations(self, headers, params=None):
        return self._request("GET", "/accommodations", headers=headers, params=params)

    def revoke_accommodation(self, accommodation_id, headers):
        return self._request("POST", f"/accommodations/{accommodation_id}/revoke", {}, headers)

    # ---- Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def verify_identity(self, appointment_id, payload, headers):
        return self._request("POST", f"/appointments/{appointment_id}/verify-identity", payload, headers)

    def list_identity_verifications(self, appointment_id, headers, params=None):
        return self._request("GET", f"/appointments/{appointment_id}/identity-verifications", headers=headers, params=params)

    def check_in(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/check-in", {}, headers)

    def mark_no_show(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/mark-no-show", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", {}, headers)

    # ---- ProctoringSession ----
    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def raise_flag(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/flags", payload, headers)

    def list_flags(self, session_id, headers, params=None):
        return self._request("GET", f"/sessions/{session_id}/flags", headers=headers, params=params)

    def pause_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/pause", {}, headers)

    def resume_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/resume", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/complete", {}, headers)

    # ---- Escalation ----
    def create_escalation(self, payload, headers):
        return self._request("POST", "/escalations", payload, headers)

    def get_escalation(self, escalation_id, headers):
        return self._request("GET", f"/escalations/{escalation_id}", headers=headers)

    def list_escalations(self, headers, params=None):
        return self._request("GET", "/escalations", headers=headers, params=params)

    def claim_escalation(self, escalation_id, headers):
        return self._request("POST", f"/escalations/{escalation_id}/claim", {}, headers)

    def decide_escalation(self, escalation_id, payload, headers):
        return self._request("POST", f"/escalations/{escalation_id}/decide", payload, headers)

    # ---- IntegrityReport ----
    def create_integrity_report(self, payload, headers):
        return self._request("POST", "/integrity-reports", payload, headers)

    def get_integrity_report(self, report_id, headers):
        return self._request("GET", f"/integrity-reports/{report_id}", headers=headers)

    def list_integrity_reports(self, headers, params=None):
        return self._request("GET", "/integrity-reports", headers=headers, params=params)

    def deliver_integrity_report(self, report_id, headers):
        return self._request("POST", f"/integrity-reports/{report_id}/deliver", {}, headers)

    # ---- RetakeAuthorization ----
    def create_retake_authorization(self, payload, headers):
        return self._request("POST", "/retake-authorizations", payload, headers)

    def get_retake_authorization(self, retake_id, headers):
        return self._request("GET", f"/retake-authorizations/{retake_id}", headers=headers)

    def list_retake_authorizations(self, headers, params=None):
        return self._request("GET", "/retake-authorizations", headers=headers, params=params)

    def rebook_retake(self, retake_id, payload, headers):
        return self._request("POST", f"/retake-authorizations/{retake_id}/rebook", payload, headers)

    def expire_retake(self, retake_id, headers):
        return self._request("POST", f"/retake-authorizations/{retake_id}/expire", {}, headers)

    # ---- Test-driving (logical clock) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
