"""API client: one method per endpoint from scaffold Table 5."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """PRD-specific endpoint methods for the Course Selection API."""

    # ------------------------------------------------------------------ Semester
    def create_semester(self, payload, headers):
        return self._request("POST", "/semesters", payload, headers)

    def list_semesters(self, headers, params=None):
        return self._request("GET", "/semesters", headers=headers, params=params)

    def get_semester(self, semester_id, headers):
        return self._request("GET", f"/semesters/{semester_id}", headers=headers)

    def open_enrollment(self, semester_id, headers):
        return self._request("POST", f"/semesters/{semester_id}/open-enrollment", headers=headers)

    def close_enrollment(self, semester_id, headers):
        return self._request("POST", f"/semesters/{semester_id}/close-enrollment", headers=headers)

    def reopen_enrollment(self, semester_id, headers):
        return self._request("POST", f"/semesters/{semester_id}/reopen-enrollment", headers=headers)

    def finalize_semester(self, semester_id, headers):
        return self._request("POST", f"/semesters/{semester_id}/finalize", headers=headers)

    # ------------------------------------------------------------------ Department
    def create_department(self, semester_id, payload, headers):
        return self._request("POST", f"/semesters/{semester_id}/departments", payload, headers)

    def list_departments(self, semester_id, headers, params=None):
        return self._request("GET", f"/semesters/{semester_id}/departments", headers=headers, params=params)

    def get_department(self, semester_id, department_id, headers):
        return self._request("GET", f"/semesters/{semester_id}/departments/{department_id}", headers=headers)

    # ------------------------------------------------------------------ Course
    def create_course(self, semester_id, department_id, payload, headers):
        return self._request(
            "POST",
            f"/semesters/{semester_id}/departments/{department_id}/courses",
            payload,
            headers,
        )

    def list_courses(self, semester_id, department_id, headers, params=None):
        return self._request(
            "GET",
            f"/semesters/{semester_id}/departments/{department_id}/courses",
            headers=headers,
            params=params,
        )

    def get_course(self, semester_id, department_id, course_id, headers):
        return self._request(
            "GET",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}",
            headers=headers,
        )

    def update_course(self, semester_id, department_id, course_id, payload, headers):
        return self._request(
            "PATCH",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}",
            payload,
            headers,
        )

    def get_prerequisite_graph(self, semester_id, department_id, course_id, headers):
        return self._request(
            "GET",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}/prerequisite-graph",
            headers=headers,
        )

    # ------------------------------------------------------------------ Section
    def create_section(self, semester_id, department_id, course_id, payload, headers):
        return self._request(
            "POST",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}/sections",
            payload,
            headers,
        )

    def list_sections(self, semester_id, department_id, course_id, headers, params=None):
        return self._request(
            "GET",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}/sections",
            headers=headers,
            params=params,
        )

    def get_section(self, semester_id, department_id, course_id, section_id, headers):
        return self._request(
            "GET",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}/sections/{section_id}",
            headers=headers,
        )

    def update_section(self, semester_id, department_id, course_id, section_id, payload, headers):
        return self._request(
            "PATCH",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}/sections/{section_id}",
            payload,
            headers,
        )

    # ------------------------------------------------------------------ Enrollment
    def create_enrollment(self, semester_id, department_id, course_id, section_id, payload, headers):
        return self._request(
            "POST",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}/sections/{section_id}/enrollments",
            payload,
            headers,
        )

    def list_enrollments(self, semester_id, department_id, course_id, section_id, headers, params=None):
        return self._request(
            "GET",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}/sections/{section_id}/enrollments",
            headers=headers,
            params=params,
        )

    def get_enrollment(self, semester_id, department_id, course_id, section_id, enrollment_id, headers):
        return self._request(
            "GET",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}/sections/{section_id}/enrollments/{enrollment_id}",
            headers=headers,
        )

    def approve_enrollment(self, semester_id, department_id, course_id, section_id, enrollment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}/sections/{section_id}/enrollments/{enrollment_id}/approve",
            payload,
            headers,
        )

    def reject_enrollment(self, semester_id, department_id, course_id, section_id, enrollment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}/sections/{section_id}/enrollments/{enrollment_id}/reject",
            payload,
            headers,
        )

    def drop_enrollment(self, semester_id, department_id, course_id, section_id, enrollment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}/sections/{section_id}/enrollments/{enrollment_id}/drop",
            payload,
            headers,
        )

    def withdraw_enrollment(self, semester_id, department_id, course_id, section_id, enrollment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/semesters/{semester_id}/departments/{department_id}/courses/{course_id}/sections/{section_id}/enrollments/{enrollment_id}/withdraw",
            payload,
            headers,
        )

    # ------------------------------------------------------------------ Instructor
    def create_instructor(self, semester_id, payload, headers):
        return self._request("POST", f"/semesters/{semester_id}/instructors", payload, headers)

    def list_instructors(self, semester_id, headers, params=None):
        return self._request("GET", f"/semesters/{semester_id}/instructors", headers=headers, params=params)

    def get_instructor(self, semester_id, instructor_id, headers):
        return self._request("GET", f"/semesters/{semester_id}/instructors/{instructor_id}", headers=headers)

    # ------------------------------------------------------------------ Student
    def create_student(self, semester_id, payload, headers):
        return self._request("POST", f"/semesters/{semester_id}/students", payload, headers)

    def list_students(self, semester_id, headers, params=None):
        return self._request("GET", f"/semesters/{semester_id}/students", headers=headers, params=params)

    def get_student(self, semester_id, student_id, headers):
        return self._request("GET", f"/semesters/{semester_id}/students/{student_id}", headers=headers)

    def update_student(self, semester_id, student_id, payload, headers):
        return self._request("PATCH", f"/semesters/{semester_id}/students/{student_id}", payload, headers)

    def get_student_schedule(self, semester_id, student_id, headers):
        return self._request("GET", f"/semesters/{semester_id}/students/{student_id}/schedule", headers=headers)

    # ------------------------------------------------------------------ CrossDeptPermission
    def create_cross_dept_permission(self, semester_id, payload, headers):
        return self._request("POST", f"/semesters/{semester_id}/cross-dept-permissions", payload, headers)

    def list_cross_dept_permissions(self, semester_id, headers, params=None):
        return self._request("GET", f"/semesters/{semester_id}/cross-dept-permissions", headers=headers, params=params)

    def get_cross_dept_permission(self, semester_id, permission_id, headers):
        return self._request("GET", f"/semesters/{semester_id}/cross-dept-permissions/{permission_id}", headers=headers)

    def revoke_cross_dept_permission(self, semester_id, permission_id, headers):
        return self._request("POST", f"/semesters/{semester_id}/cross-dept-permissions/{permission_id}/revoke", headers=headers)

    # ------------------------------------------------------------------ Diagnostic
    def list_schedule_conflicts(self, semester_id, headers, params=None):
        return self._request("GET", f"/semesters/{semester_id}/schedule-conflicts", headers=headers, params=params)

    def list_waitlist_promotions(self, semester_id, headers, params=None):
        return self._request("GET", f"/semesters/{semester_id}/waitlist-promotions", headers=headers, params=params)


api_client = ApiClient()
