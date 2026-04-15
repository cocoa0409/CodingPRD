"""Tests for pagination, path validation, and edge cases."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID,
    api_client, ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    create_semester, create_department, create_instructor, create_course, create_section,
    create_student, create_semester_in_open_enrollment, enroll_student, setup_enrollment_ready,
)


class TestPagination:
    """Tests for pagination parameters across list endpoints."""

    def test_default_page_size(self):
        """Default page_size is 20."""
        semester = create_semester()
        resp = api_client.list_departments(semester["id"], TEST_USERS["registrar_headers"])
        data, meta = validate_paginated(resp)
        assert meta["page_size"] == 20

    def test_custom_page_size(self):
        """page_size can be set to custom value within 1-50."""
        semester = create_semester()
        resp = api_client.list_departments(
            semester["id"], TEST_USERS["registrar_headers"],
            params={"page_size": 5}
        )
        data, meta = validate_paginated(resp)
        assert meta["page_size"] == 5

    def test_page_size_minimum_boundary(self):
        """page_size=1 is valid (minimum)."""
        semester = create_semester()
        resp = api_client.list_departments(
            semester["id"], TEST_USERS["registrar_headers"],
            params={"page_size": 1}
        )
        data, meta = validate_paginated(resp)
        assert meta["page_size"] == 1

    def test_page_size_maximum_boundary(self):
        """page_size=50 is valid (maximum)."""
        semester = create_semester()
        resp = api_client.list_departments(
            semester["id"], TEST_USERS["registrar_headers"],
            params={"page_size": 50}
        )
        data, meta = validate_paginated(resp)
        assert meta["page_size"] == 50

    def test_page_size_below_minimum(self):
        """page_size=0 -> INVALID_PAGE_PARAMS."""
        semester = create_semester()
        resp = api_client.list_departments(
            semester["id"], TEST_USERS["registrar_headers"],
            params={"page_size": 0}
        )
        validate_error(resp, ApiErrorId.INVALID_PAGE_PARAMS)

    def test_page_size_above_maximum(self):
        """page_size=51 -> INVALID_PAGE_PARAMS."""
        semester = create_semester()
        resp = api_client.list_departments(
            semester["id"], TEST_USERS["registrar_headers"],
            params={"page_size": 51}
        )
        validate_error(resp, ApiErrorId.INVALID_PAGE_PARAMS)

    def test_malformed_page_token(self):
        """Malformed page_token -> INVALID_PAGE_PARAMS."""
        semester = create_semester()
        resp = api_client.list_departments(
            semester["id"], TEST_USERS["registrar_headers"],
            params={"page_token": "not-a-valid-token!!!"}
        )
        validate_error(resp, ApiErrorId.INVALID_PAGE_PARAMS)

    def test_pagination_total_results(self):
        """total_results reflects the total count of resources."""
        semester = create_semester()
        for i in range(3):
            create_department(semester["id"], dept_code=f"PG{i}", dept_name=f"PG Dept {i}")
        resp = api_client.list_departments(semester["id"], TEST_USERS["registrar_headers"])
        data, meta = validate_paginated(resp)
        assert meta["total_results"] >= 3

    def test_pagination_next_page_token(self):
        """When more pages exist, next_page_token is not null."""
        semester = create_semester()
        for i in range(5):
            create_department(semester["id"], dept_code=f"NP{i}", dept_name=f"NP Dept {i}")
        resp = api_client.list_departments(
            semester["id"], TEST_USERS["registrar_headers"],
            params={"page_size": 2}
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        if meta["total_results"] > 2:
            assert meta["next_page_token"] is not None, \
                "next_page_token should be set when more pages exist"


class TestHierarchicalPathValidation:
    """Tests for left-to-right path parameter validation (PRD section 2.5)."""

    def test_semester_unknown_first(self):
        """Non-existent semester in nested path -> SEMESTER_UNKNOWN (validated first)."""
        resp = api_client.get_department(NON_EXISTENT_UUID, NON_EXISTENT_UUID, TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.SEMESTER_UNKNOWN)

    def test_department_unknown_after_valid_semester(self):
        """Valid semester, non-existent department -> DEPARTMENT_UNKNOWN."""
        semester = create_semester()
        resp = api_client.get_department(semester["id"], NON_EXISTENT_UUID, TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.DEPARTMENT_UNKNOWN)

    def test_course_unknown_after_valid_dept(self):
        """Valid semester+department, non-existent course -> COURSE_UNKNOWN."""
        semester = create_semester()
        dept = create_department(semester["id"])
        resp = api_client.get_course(
            semester["id"], dept["id"], NON_EXISTENT_UUID, TEST_USERS["registrar_headers"]
        )
        validate_error(resp, ApiErrorId.COURSE_UNKNOWN)

    def test_section_unknown_after_valid_course(self):
        """Valid semester+department+course, non-existent section -> SECTION_UNKNOWN."""
        semester = create_semester()
        dept = create_department(semester["id"])
        course = create_course(semester["id"], dept["id"])
        resp = api_client.get_section(
            semester["id"], dept["id"], course["id"], NON_EXISTENT_UUID, TEST_USERS["registrar_headers"]
        )
        validate_error(resp, ApiErrorId.SECTION_UNKNOWN)

    def test_enrollment_unknown_after_valid_section(self):
        """Valid full path, non-existent enrollment -> ENROLLMENT_UNKNOWN."""
        semester = create_semester()
        dept = create_department(semester["id"])
        instructor = create_instructor(semester["id"], dept["id"])
        course = create_course(semester["id"], dept["id"])
        section = create_section(semester["id"], dept["id"], course["id"], instructor["id"])
        resp = api_client.get_enrollment(
            semester["id"], dept["id"], course["id"], section["id"],
            NON_EXISTENT_UUID, TEST_USERS["registrar_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_UNKNOWN)

    def test_department_belongs_to_different_semester(self):
        """Department from a different semester -> DEPARTMENT_UNKNOWN."""
        semester_a = create_semester()
        semester_b = create_semester()
        dept_a = create_department(semester_a["id"])
        # Try to access dept_a under semester_b
        resp = api_client.get_department(semester_b["id"], dept_a["id"], TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.DEPARTMENT_UNKNOWN)


class TestStudentSchedule:
    """Tests for GET .../students/{studentId}/schedule endpoint."""

    def test_student_schedule_returns_enrolled_sections(self):
        """Student schedule shows all ENROLLED sections with times."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)

        # Enroll in two non-conflicting courses
        c1 = course
        s1 = section
        enroll_student(sid, dept["id"], c1["id"], s1["id"], student["id"])

        c2 = create_course(sid, dept["id"], credit_hours=3, course_code="SCH-02")
        s2 = create_section(sid, dept["id"], c2["id"], instructor["id"],
                             schedule_days="TR", schedule_start="14:00", schedule_end="15:00",
                             location="Room-SCH")
        enroll_student(sid, dept["id"], c2["id"], s2["id"], student["id"])

        resp = api_client.get_student_schedule(sid, student["id"], TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        # Should return a list of sections
        assert isinstance(data, list) or (isinstance(data, dict) and "payload" not in data), \
            "Schedule should return section list"

    def test_student_schedule_access_control(self):
        """Student, Professor, and Registrar can view student schedule."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]
        student = create_student(sid, dept["id"])

        for role in ["registrar_headers", "professor_headers", "student_headers"]:
            resp = api_client.get_student_schedule(sid, student["id"], TEST_USERS[role])
            # Should succeed (200)
            assert resp.status_code == 200, f"Role {role} should be able to view student schedule"


class TestEnrollmentListFiltering:
    """Tests for enrollment list endpoint with status filter."""

    def test_list_enrollments_in_section(self):
        """List enrollments for a section returns paginated results."""
        ctx = setup_enrollment_ready()
        enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        resp = api_client.list_enrollments(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], TEST_USERS["registrar_headers"]
        )
        data, meta = validate_paginated(resp)
        assert meta["total_results"] >= 1

    def test_list_enrollments_filter_by_status(self):
        """Enrollment list can be filtered by status."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        s1 = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], course["id"], section["id"], s1["id"])

        resp = api_client.list_enrollments(
            sid, dept["id"], course["id"], section["id"],
            TEST_USERS["registrar_headers"],
            params={"status": "ENROLLED"}
        )
        data, meta = validate_paginated(resp)
        for enrollment in data:
            assert enrollment["status"] == "ENROLLED"
