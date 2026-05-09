"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Students ──────────────────────────────────────────────────
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def get_student_degree_plan(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}/degree-plan", headers=headers)

    def get_student_recommendations(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}/recommendations", headers=headers)

    def get_student_sync_events(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/sync-events", headers=headers, params=params)

    # ─── Departments / Campuses / Professors / Lab Equipment ───────
    def create_department(self, payload, headers):
        return self._request("POST", "/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", headers=headers)

    def create_campus(self, payload, headers):
        return self._request("POST", "/campuses", payload, headers)

    def create_professor(self, payload, headers):
        return self._request("POST", "/professors", payload, headers)

    def create_lab_equipment(self, payload, headers):
        return self._request("POST", "/lab-equipment", payload, headers)

    # ─── Terms ────────────────────────────────────────────────────
    def create_term(self, payload, headers):
        return self._request("POST", "/terms", payload, headers)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/terms/{term_id}", headers=headers)

    def conclude_term(self, term_id, headers):
        return self._request("POST", f"/terms/{term_id}/conclude", headers=headers)

    # ─── Courses ──────────────────────────────────────────────────
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    # ─── Course Offerings ─────────────────────────────────────────
    def create_course_offering(self, payload, headers):
        return self._request("POST", "/course-offerings", payload, headers)

    def list_course_offerings(self, headers, params=None):
        return self._request("GET", "/course-offerings", headers=headers, params=params)

    def get_course_offering(self, offering_id, headers):
        return self._request("GET", f"/course-offerings/{offering_id}", headers=headers)

    def open_course_offering(self, offering_id, headers):
        return self._request("POST", f"/course-offerings/{offering_id}/open", headers=headers)

    def close_course_offering(self, offering_id, headers):
        return self._request("POST", f"/course-offerings/{offering_id}/close", headers=headers)

    def patch_course_offering_capacity(self, offering_id, payload, headers):
        return self._request("PATCH", f"/course-offerings/{offering_id}/capacity", payload, headers)

    def get_course_offering_waitlist(self, offering_id, headers, params=None):
        return self._request("GET", f"/course-offerings/{offering_id}/waitlist", headers=headers, params=params)

    # ─── Enrollment Requests ──────────────────────────────────────
    def create_enrollment_request(self, payload, headers):
        return self._request("POST", "/enrollment-requests", payload, headers)

    def get_enrollment_request(self, request_id, headers):
        return self._request("GET", f"/enrollment-requests/{request_id}", headers=headers)

    def list_enrollment_requests(self, headers, params=None):
        return self._request("GET", "/enrollment-requests", headers=headers, params=params)

    def cancel_enrollment_request(self, request_id, headers):
        return self._request("POST", f"/enrollment-requests/{request_id}/cancel", headers=headers)

    def settle_tuition(self, request_id, headers):
        return self._request("POST", f"/enrollment-requests/{request_id}/settle-tuition", headers=headers)

    # ─── Over-Limit Applications ──────────────────────────────────
    def create_over_limit_application(self, payload, headers):
        return self._request("POST", "/over-limit-applications", payload, headers)

    def get_over_limit_application(self, application_id, headers):
        return self._request("GET", f"/over-limit-applications/{application_id}", headers=headers)

    def submit_over_limit_application(self, application_id, headers):
        return self._request("POST", f"/over-limit-applications/{application_id}/submit", headers=headers)

    def sign_over_limit_application(self, application_id, payload, headers):
        return self._request("POST", f"/over-limit-applications/{application_id}/sign", payload, headers)

    def reject_over_limit_application(self, application_id, payload, headers):
        return self._request("POST", f"/over-limit-applications/{application_id}/reject", payload, headers)

    def revise_over_limit_application(self, application_id, headers):
        return self._request("POST", f"/over-limit-applications/{application_id}/revise", headers=headers)

    # ─── Department Access Grants ─────────────────────────────────
    def create_department_access_grant(self, payload, headers):
        return self._request("POST", "/department-access-grants", payload, headers)

    def list_department_access_grants(self, headers, params=None):
        return self._request("GET", "/department-access-grants", headers=headers, params=params)

    def revoke_department_access_grant(self, grant_id, headers):
        return self._request("POST", f"/department-access-grants/{grant_id}/revoke", headers=headers)

    # ─── Credit Equivalence Policies ──────────────────────────────
    def create_credit_equivalence_policy(self, payload, headers):
        return self._request("POST", "/credit-equivalence-policies", payload, headers)

    def list_credit_equivalence_policies(self, headers, params=None):
        return self._request("GET", "/credit-equivalence-policies", headers=headers, params=params)

    # ─── Test-driving capabilities ────────────────────────────────
    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)

    def run_sweep(self, headers):
        return self._request("POST", "/_sweep/run", headers=headers)


api_client = ApiClient()
