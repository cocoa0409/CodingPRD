"""API client: one method per endpoint defined in the PRD.

All routes are mounted at the root; every collection is a top-level path segment.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- logical clock
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------ state jurisdictions
    def create_state_jurisdiction(self, payload, headers):
        return self._request("POST", "/state-jurisdictions", payload, headers)

    # ------------------------------------------------------------------------ courses
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def revise_course(self, course_id, payload, headers):
        return self._request("PATCH", f"/courses/{course_id}", payload, headers)

    def publish_course(self, course_id, headers, payload=None):
        return self._request("POST", f"/courses/{course_id}/publish", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    # ---------------------------------------------------------------- course approvals
    def create_course_approval(self, payload, headers):
        return self._request("POST", "/course-approvals", payload, headers)

    def decide_course_approval(self, approval_id, payload, headers):
        return self._request("POST", f"/course-approvals/{approval_id}/decision",
                             payload, headers)

    def resubmit_course_approval(self, approval_id, payload, headers):
        return self._request("POST", f"/course-approvals/{approval_id}/resubmit",
                             payload, headers)

    def get_course_approval(self, approval_id, headers):
        return self._request("GET", f"/course-approvals/{approval_id}", headers=headers)

    def list_course_approvals(self, headers, params=None):
        return self._request("GET", "/course-approvals", headers=headers, params=params)

    # ----------------------------------------------------------------------- trainers
    def create_trainer(self, payload, headers):
        return self._request("POST", "/trainers", payload, headers)

    def credential_trainer(self, trainer_id, payload, headers):
        return self._request("POST", f"/trainers/{trainer_id}/credential", payload, headers)

    def suspend_trainer(self, trainer_id, payload, headers):
        return self._request("POST", f"/trainers/{trainer_id}/suspend", payload, headers)

    def get_trainer(self, trainer_id, headers):
        return self._request("GET", f"/trainers/{trainer_id}", headers=headers)

    # ------------------------------------------------------------------ class sessions
    def create_class_session(self, payload, headers):
        return self._request("POST", "/class-sessions", payload, headers)

    def lock_roster(self, session_id, headers, payload=None):
        return self._request("POST", f"/class-sessions/{session_id}/lock-roster",
                             payload, headers)

    def open_exam(self, session_id, payload, headers):
        return self._request("POST", f"/class-sessions/{session_id}/open-exam",
                             payload, headers)

    def complete_class_session(self, session_id, headers, payload=None):
        return self._request("POST", f"/class-sessions/{session_id}/complete",
                             payload, headers)

    def cancel_class_session(self, session_id, payload, headers):
        return self._request("POST", f"/class-sessions/{session_id}/cancel",
                             payload, headers)

    def get_class_session(self, session_id, headers):
        return self._request("GET", f"/class-sessions/{session_id}", headers=headers)

    def list_class_sessions(self, headers, params=None):
        return self._request("GET", "/class-sessions", headers=headers, params=params)

    # ---------------------------------------------------------------- alcohol servers
    def create_alcohol_server(self, payload, headers):
        return self._request("POST", "/alcohol-servers", payload, headers)

    def get_alcohol_server(self, server_id, headers):
        return self._request("GET", f"/alcohol-servers/{server_id}", headers=headers)

    def list_alcohol_servers(self, headers, params=None):
        return self._request("GET", "/alcohol-servers", headers=headers, params=params)

    def list_server_assignments_for_server(self, server_id, headers, params=None):
        return self._request("GET", f"/alcohol-servers/{server_id}/server-assignments",
                             headers=headers, params=params)

    # -------------------------------------------------------------------- enrollments
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def mark_attendance(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/attendance",
                             payload, headers)

    def withdraw_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw",
                             payload, headers)

    def open_exam_attempt(self, enrollment_id, headers, payload=None):
        return self._request("POST", f"/enrollments/{enrollment_id}/exam-attempts",
                             payload, headers)

    def submit_exam_attempt(self, attempt_id, payload, headers):
        return self._request("POST", f"/exam-attempts/{attempt_id}/submit", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def list_exam_attempts(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/exam-attempts",
                             headers=headers, params=params)

    # ------------------------------------------------------------------- certificates
    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def transmit_certificate(self, certificate_id, headers, payload=None):
        return self._request("POST", f"/certificates/{certificate_id}/registry-submissions",
                             payload, headers)

    def acknowledge_registry_submission(self, submission_id, payload, headers):
        return self._request("POST", f"/registry-submissions/{submission_id}/acknowledge",
                             payload, headers)

    def list_registry_submissions(self, certificate_id, headers, params=None):
        return self._request("GET", f"/certificates/{certificate_id}/registry-submissions",
                             headers=headers, params=params)

    # --------------------------------------------------------------- employer accounts
    def create_employer_account(self, payload, headers):
        return self._request("POST", "/employer-accounts", payload, headers)

    def set_employer_account_status(self, account_id, payload, headers):
        return self._request("POST", f"/employer-accounts/{account_id}/status",
                             payload, headers)

    def purchase_seat_credits(self, account_id, payload, headers):
        return self._request("POST",
                             f"/employer-accounts/{account_id}/seat-credit-purchases",
                             payload, headers)

    def create_employer_location(self, account_id, payload, headers):
        return self._request("POST", f"/employer-accounts/{account_id}/locations",
                             payload, headers)

    def issue_dram_shop_document(self, account_id, payload, headers):
        return self._request("POST",
                             f"/employer-accounts/{account_id}/dram-shop-documents",
                             payload, headers)

    def get_employer_account(self, account_id, headers):
        return self._request("GET", f"/employer-accounts/{account_id}", headers=headers)

    def list_dram_shop_documents(self, account_id, headers, params=None):
        return self._request("GET", f"/employer-accounts/{account_id}/dram-shop-documents",
                             headers=headers, params=params)

    # -------------------------------------------------------------- employer locations
    def get_employer_location(self, location_id, headers):
        return self._request("GET", f"/employer-locations/{location_id}", headers=headers)

    def list_employer_locations(self, headers, params=None):
        return self._request("GET", "/employer-locations", headers=headers, params=params)

    def get_location_compliance_dashboard(self, location_id, headers):
        return self._request("GET",
                             f"/employer-locations/{location_id}/compliance-dashboard",
                             headers=headers)

    def create_server_assignment(self, location_id, payload, headers):
        return self._request("POST",
                             f"/employer-locations/{location_id}/server-assignments",
                             payload, headers)

    def end_server_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/server-assignments/{assignment_id}/end",
                             payload, headers)

    def list_location_server_assignments(self, location_id, headers, params=None):
        return self._request("GET",
                             f"/employer-locations/{location_id}/server-assignments",
                             headers=headers, params=params)

    # ----------------------------------------------------------------- compliance runs
    def create_compliance_run(self, headers, payload=None):
        return self._request("POST", "/compliance-runs", payload, headers)


api_client = ApiClient()
