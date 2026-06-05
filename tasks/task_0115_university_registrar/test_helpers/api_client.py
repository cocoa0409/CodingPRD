"""API client: one method per endpoint defined in the University Registrar PRD."""
import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # Per-test-server isolation kills and relaunches the server on the SAME
        # port before every test, while this module-level client (and its
        # requests.Session connection pool) lives for the whole pytest process.
        # A pooled keep-alive connection opened in a prior test points at the
        # now-dead server socket; reusing it for the first request of the next
        # test surfaces as an intermittent ConnectionError/BadStatusLine. Forcing
        # "Connection: close" makes the server close each socket after responding,
        # which minimizes pooling. Transport-only — no payload/assertion change.
        self.session.headers["Connection"] = "close"

    def _request(self, method, path, payload=None, headers=None, params=None):
        # Belt-and-suspenders for the restart-on-same-port race above: urllib3's
        # is_connection_dropped check has a window right after the kill where a
        # stale pooled socket still looks alive, so the request gets written to a
        # dead connection and comes back as a ConnectionError (e.g. BadStatusLine).
        # That request never reached the live server, so retrying once on a fresh
        # connection is safe and deterministic. Only genuine transport drops are
        # retried — a real server-side error returns an HTTP 4xx/5xx response
        # (not a ConnectionError), so this never masks an implementation fault.
        try:
            return super()._request(method, path, payload, headers, params)
        except requests.exceptions.ConnectionError:
            self.session.close()  # discard any stale pooled sockets
            return super()._request(method, path, payload, headers, params)

    # ---- Term ----
    def create_term(self, payload, headers):
        return self._request("POST", "/terms", payload, headers)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/terms/{term_id}", headers=headers)

    def set_term_status(self, term_id, payload, headers):
        return self._request("POST", f"/terms/{term_id}/status", payload, headers)

    def list_term_sections(self, term_id, headers, params=None):
        return self._request("GET", f"/terms/{term_id}/sections", headers=headers, params=params)

    def list_term_enrollments(self, term_id, headers, params=None):
        return self._request("GET", f"/terms/{term_id}/enrollments", headers=headers, params=params)

    def list_term_appointments(self, term_id, headers, params=None):
        return self._request("GET", f"/terms/{term_id}/appointments", headers=headers, params=params)

    # ---- Program ----
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_program_students(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/students", headers=headers, params=params)

    def list_program_courses(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/courses", headers=headers, params=params)

    # ---- Course & requirements ----
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def add_course_requirement(self, course_id, payload, headers):
        return self._request("POST", f"/courses/{course_id}/requirements", payload, headers)

    def list_course_requirements(self, course_id, headers, params=None):
        return self._request("GET", f"/courses/{course_id}/requirements", headers=headers, params=params)

    def list_course_sections(self, course_id, headers, params=None):
        return self._request("GET", f"/courses/{course_id}/sections", headers=headers, params=params)

    # ---- Instructor ----
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    def list_instructor_sections(self, instructor_id, headers, params=None):
        return self._request("GET", f"/instructors/{instructor_id}/sections", headers=headers, params=params)

    # ---- Section ----
    def create_section(self, payload, headers):
        return self._request("POST", "/sections", payload, headers)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/sections/{section_id}", headers=headers)

    def set_section_status(self, section_id, payload, headers):
        return self._request("POST", f"/sections/{section_id}/status", payload, headers)

    def list_section_enrollments(self, section_id, headers, params=None):
        return self._request("GET", f"/sections/{section_id}/enrollments", headers=headers, params=params)

    # ---- Student ----
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_student_enrollments(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/enrollments", headers=headers, params=params)

    def list_student_holds(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/holds", headers=headers, params=params)

    def get_transcript(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/transcript", headers=headers, params=params)

    def get_degree_audit(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/degree-audit", headers=headers, params=params)

    def list_student_swap_requests(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/swap-requests", headers=headers, params=params)

    def list_student_appointments(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/appointments", headers=headers, params=params)

    def list_student_refunds(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/refunds", headers=headers, params=params)

    # ---- Enrollment Appointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    # ---- Enrollment (registration) ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def drop_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/drop", payload={}, headers=headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", payload={}, headers=headers)

    def grade_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/grade", payload, headers)

    def list_enrollment_refunds(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/refunds", headers=headers, params=params)

    # ---- Hold ----
    def create_hold(self, payload, headers):
        return self._request("POST", "/holds", payload, headers)

    def clear_hold(self, hold_id, headers):
        return self._request("POST", f"/holds/{hold_id}/clear", payload={}, headers=headers)

    # ---- Swap ----
    def create_swap_request(self, payload, headers):
        return self._request("POST", "/swap-requests", payload, headers)

    def list_swap_requests(self, headers, params=None):
        return self._request("GET", "/swap-requests", headers=headers, params=params)

    def get_swap_request(self, swap_id, headers):
        return self._request("GET", f"/swap-requests/{swap_id}", headers=headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)


api_client = ApiClient()
