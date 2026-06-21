"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() does the HTTP work. Every
method returns the raw requests.Response so tests can assert status codes.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Employees --------------------------------------------------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    def get_employee_dashboard(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}/dashboard", headers=headers)

    # ---- Courses ----------------------------------------------------------
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def publish_course(self, course_id, headers):
        return self._request("POST", f"/courses/{course_id}/publish", {}, headers)

    def archive_course(self, course_id, headers):
        return self._request("POST", f"/courses/{course_id}/archive", {}, headers)

    def add_course_prerequisite(self, course_id, payload, headers):
        return self._request("POST", f"/courses/{course_id}/prerequisites", payload, headers)

    def list_course_prerequisites(self, headers, params=None):
        return self._request("GET", "/course-prerequisites", headers=headers, params=params)

    def get_course_prerequisite(self, prereq_id, headers):
        return self._request("GET", f"/course-prerequisites/{prereq_id}", headers=headers)

    # ---- Learning paths ---------------------------------------------------
    def create_learning_path(self, payload, headers):
        return self._request("POST", "/learning-paths", payload, headers)

    def get_learning_path(self, path_id, headers):
        return self._request("GET", f"/learning-paths/{path_id}", headers=headers)

    def add_path_step(self, path_id, payload, headers):
        return self._request("POST", f"/learning-paths/{path_id}/steps", payload, headers)

    def list_path_steps_under_path(self, path_id, headers, params=None):
        return self._request("GET", f"/learning-paths/{path_id}/steps", headers=headers, params=params)

    def publish_learning_path(self, path_id, headers):
        return self._request("POST", f"/learning-paths/{path_id}/publish", {}, headers)

    def archive_learning_path(self, path_id, headers):
        return self._request("POST", f"/learning-paths/{path_id}/archive", {}, headers)

    def list_path_steps(self, headers, params=None):
        return self._request("GET", "/path-steps", headers=headers, params=params)

    def get_path_step(self, step_id, headers):
        return self._request("GET", f"/path-steps/{step_id}", headers=headers)

    # ---- Assignment rules -------------------------------------------------
    def create_assignment_rule(self, payload, headers):
        return self._request("POST", "/assignment-rules", payload, headers)

    def list_assignment_rules(self, headers, params=None):
        return self._request("GET", "/assignment-rules", headers=headers, params=params)

    def get_assignment_rule(self, rule_id, headers):
        return self._request("GET", f"/assignment-rules/{rule_id}", headers=headers)

    def apply_assignment_rule(self, rule_id, headers):
        return self._request("POST", f"/assignment-rules/{rule_id}/apply", {}, headers)

    # ---- Enrollments ------------------------------------------------------
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def start_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/start", {}, headers)

    def create_quiz_attempt(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/quiz-attempts", payload, headers)

    def list_quiz_attempts(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/quiz-attempts", headers=headers, params=params)

    def reopen_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/reopen", {}, headers)

    def waive_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/waive", {}, headers)

    # ---- Tracking sessions ------------------------------------------------
    def open_tracking_session(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/tracking-sessions", {}, headers)

    def list_tracking_sessions(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/tracking-sessions", headers=headers, params=params)

    def commit_tracking_session(self, session_id, payload, headers):
        return self._request("PATCH", f"/tracking-sessions/{session_id}/commit", payload, headers)

    def terminate_tracking_session(self, session_id, headers, payload=None):
        return self._request("POST", f"/tracking-sessions/{session_id}/terminate", payload or {}, headers)

    # ---- Path enrollments -------------------------------------------------
    def create_path_enrollment(self, payload, headers):
        return self._request("POST", "/path-enrollments", payload, headers)

    def list_path_enrollments(self, headers, params=None):
        return self._request("GET", "/path-enrollments", headers=headers, params=params)

    def get_path_enrollment(self, path_enrollment_id, headers):
        return self._request("GET", f"/path-enrollments/{path_enrollment_id}", headers=headers)

    # ---- Certificates -----------------------------------------------------
    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def revoke_certificate(self, certificate_id, headers):
        return self._request("POST", f"/certificates/{certificate_id}/revoke", {}, headers)

    # ---- Escalations ------------------------------------------------------
    def run_escalations(self, headers):
        return self._request("POST", "/escalations/run", {}, headers)

    def list_escalation_events(self, headers, params=None):
        return self._request("GET", "/escalation-events", headers=headers, params=params)

    def get_escalation_event(self, event_id, headers):
        return self._request("GET", f"/escalation-events/{event_id}", headers=headers)

    def acknowledge_escalation_event(self, event_id, headers):
        return self._request("POST", f"/escalation-events/{event_id}/acknowledge", {}, headers)

    # ---- Clock ------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
