"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ───────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Nurse ───────────────────────────────────────
    def create_nurse(self, payload, headers):
        return self._request("POST", "/nurses", payload, headers)

    def get_nurse(self, nurse_id, headers):
        return self._request("GET", f"/nurses/{nurse_id}", headers=headers)

    # ─── Supervisor ──────────────────────────────────
    def create_supervisor(self, payload, headers):
        return self._request("POST", "/supervisors", payload, headers)

    # ─── Client ──────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def record_consent(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/consent", {}, headers)

    def get_client_risk(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/risk", headers=headers, params=params
        )

    # ─── Enrollment ──────────────────────────────────
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/activate-enrollment", {}, headers
        )

    def record_birth(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/record-birth", payload, headers
        )

    def advance_phase(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/advance-phase", {}, headers
        )

    def graduate_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/graduate", {}, headers
        )

    def disenroll(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/disenroll", {}, headers
        )

    def get_dosage(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/dosage", headers=headers, params=params
        )

    # ─── Assignment ──────────────────────────────────
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def end_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/end", {}, headers
        )

    # ─── Visit ───────────────────────────────────────
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def complete_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/visits/{visit_id}/complete", payload, headers
        )

    def revert_completion(self, visit_id, headers):
        return self._request(
            "POST", f"/visits/{visit_id}/revert-completion", {}, headers
        )

    def mark_missed(self, visit_id, headers):
        return self._request(
            "POST", f"/visits/{visit_id}/mark-missed", {}, headers
        )

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    def reschedule_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/visits/{visit_id}/reschedule", payload, headers
        )

    # ─── Assessment ──────────────────────────────────
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    # ─── Referral ────────────────────────────────────
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def contact_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/contact", {}, headers)

    def connect_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/connect", {}, headers)

    def decline_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/decline", {}, headers)

    def reopen_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/reopen", {}, headers)

    def close_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/close", {}, headers)

    # ─── SupervisionSession ──────────────────────────
    def create_supervision_session(self, payload, headers):
        return self._request("POST", "/supervision-sessions", payload, headers)

    def get_supervision_session(self, session_id, headers):
        return self._request(
            "GET", f"/supervision-sessions/{session_id}", headers=headers
        )

    def list_supervision_sessions(self, headers, params=None):
        return self._request(
            "GET", "/supervision-sessions", headers=headers, params=params
        )

    def sign_supervision_session(self, session_id, headers):
        return self._request(
            "POST", f"/supervision-sessions/{session_id}/sign", {}, headers
        )

    # ─── OutcomeMeasure ──────────────────────────────
    def create_outcome_measure(self, payload, headers):
        return self._request("POST", "/outcome-measures", payload, headers)

    def get_outcome_measure(self, measure_id, headers):
        return self._request(
            "GET", f"/outcome-measures/{measure_id}", headers=headers
        )

    def list_outcome_measures(self, headers, params=None):
        return self._request(
            "GET", "/outcome-measures", headers=headers, params=params
        )

    # ─── MiechvReport ────────────────────────────────
    def create_miechv_report(self, payload, headers):
        return self._request("POST", "/miechv-reports", payload, headers)

    def get_miechv_report(self, report_id, headers):
        return self._request("GET", f"/miechv-reports/{report_id}", headers=headers)

    def finalize_miechv_report(self, report_id, headers):
        return self._request(
            "POST", f"/miechv-reports/{report_id}/finalize", {}, headers
        )


api_client = ApiClient()
