"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The runner restarts the server before every test (per-test-server
        # isolation). A pooled keep-alive connection outlives the server
        # process that accepted it, so the first request of the next test can
        # hit a half-open socket and fail with ConnectionResetError /
        # RemoteDisconnected. Sending Connection: close forces a fresh TCP
        # connection per request, making every test talk only to its own
        # freshly booted server instance.
        self.session.headers["Connection"] = "close"

    # --- Logical clock (SystemAdmin) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Programs / requirement groups / honors policies ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def retire_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/retire", {}, headers)

    def create_requirement_group(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/requirement-groups", payload, headers)

    def list_requirement_groups(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/requirement-groups", headers=headers, params=params)

    def create_honors_policy(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/honors-policies", payload, headers)

    def list_honors_policies(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/honors-policies", headers=headers, params=params)

    def list_program_student_programs(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/student-programs", headers=headers, params=params)

    def list_program_audits(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/audits", headers=headers, params=params)

    # --- Courses ---
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    # --- Students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    # --- Enrollments ---
    def create_enrollment(self, student_id, payload, headers):
        return self._request("POST", f"/students/{student_id}/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def post_grade(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/post-grade", payload, headers)

    def change_grade(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/grade-changes", payload, headers)

    # --- Program declarations (StudentProgram) ---
    def declare_program(self, student_id, payload, headers):
        return self._request("POST", f"/students/{student_id}/programs", payload, headers)

    def list_student_programs(self, headers, params=None):
        return self._request("GET", "/student-programs", headers=headers, params=params)

    def get_student_program(self, student_program_id, headers):
        return self._request("GET", f"/student-programs/{student_program_id}", headers=headers)

    def withdraw_student_program(self, student_program_id, headers):
        return self._request("POST", f"/student-programs/{student_program_id}/withdraw", {}, headers)

    # --- Degree audits ---
    def create_audit(self, student_program_id, payload, headers):
        return self._request("POST", f"/student-programs/{student_program_id}/audits", payload, headers)

    def list_audits(self, student_program_id, headers, params=None):
        return self._request("GET", f"/student-programs/{student_program_id}/audits", headers=headers, params=params)

    # --- Substitution / waiver exceptions ---
    def create_waiver(self, student_program_id, payload, headers):
        return self._request("POST", f"/student-programs/{student_program_id}/waivers", payload, headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/substitution-waivers", headers=headers, params=params)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/substitution-waivers/{waiver_id}", headers=headers)

    def advisor_decision(self, waiver_id, payload, headers):
        return self._request("POST", f"/substitution-waivers/{waiver_id}/advisor-decision", payload, headers)

    def registrar_decision(self, waiver_id, payload, headers):
        return self._request("POST", f"/substitution-waivers/{waiver_id}/registrar-decision", payload, headers)

    def resubmit_waiver(self, waiver_id, payload, headers):
        return self._request("POST", f"/substitution-waivers/{waiver_id}/resubmit", payload, headers)

    def revoke_waiver(self, waiver_id, payload, headers):
        return self._request("POST", f"/substitution-waivers/{waiver_id}/revoke", payload, headers)

    # --- Graduation applications ---
    def create_application(self, student_program_id, payload, headers):
        return self._request("POST", f"/student-programs/{student_program_id}/applications", payload, headers)

    def list_applications(self, student_program_id, headers, params=None):
        return self._request("GET", f"/student-programs/{student_program_id}/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit", {}, headers)

    def begin_review(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/begin-review", {}, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/decide", payload, headers)

    def confer_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/confer", {}, headers)

    # --- Diplomas ---
    def list_diplomas(self, headers, params=None):
        return self._request("GET", "/diplomas", headers=headers, params=params)

    def get_diploma(self, diploma_id, headers):
        return self._request("GET", f"/diplomas/{diploma_id}", headers=headers)

    def issue_diploma(self, diploma_id, headers):
        return self._request("POST", f"/diplomas/{diploma_id}/issue", {}, headers)

    def revoke_diploma(self, diploma_id, payload, headers):
        return self._request("POST", f"/diplomas/{diploma_id}/revoke", payload, headers)

    def reissue_diploma(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/diplomas/reissue", payload, headers)


api_client = ApiClient()
