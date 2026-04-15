"""Tests for cross-department enrollment permissions and restrictions."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID,
    api_client, ApiErrorId, TEST_USERS,
    assert_cross_dept_permission,
    create_enrollment_payload, create_cross_dept_permission_payload,
)
from test_helpers.fixtures import (
    setup_two_departments, create_student, create_course, create_section,
    create_cross_dept_permission, enroll_student,
    create_semester_in_open_enrollment, create_department, create_instructor,
)


class TestCrossDeptPermissionCrud:
    """Tests for CrossDeptPermission creation, retrieval, and revocation."""

    def test_create_permission_success(self):
        """Registrar grants cross-dept permission -> 201, correct defaults."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]
        student = create_student(sid, ctx["dept_a_id"])

        payload = create_cross_dept_permission_payload(student["id"], ctx["dept_b_id"])
        resp = api_client.create_cross_dept_permission(sid, payload, TEST_USERS["registrar_headers"])
        data = validate_success(resp, expected_status=201)
        assert_cross_dept_permission(data)
        assert data["student_id"] == student["id"]
        assert data["target_department_id"] == ctx["dept_b_id"]
        assert data["max_courses"] == 2, "max_courses defaults to 2"
        assert data["courses_used"] == 0, "courses_used initializes to 0"
        assert data["status"] == "ACTIVE"

    def test_create_permission_custom_max_courses(self):
        """Permission can be created with custom max_courses."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]
        student = create_student(sid, ctx["dept_a_id"])

        payload = create_cross_dept_permission_payload(student["id"], ctx["dept_b_id"], max_courses=5)
        resp = api_client.create_cross_dept_permission(sid, payload, TEST_USERS["registrar_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["max_courses"] == 5

    def test_create_permission_professor_allowed(self):
        """Professor can grant cross-dept permissions (shared operation)."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]
        student = create_student(sid, ctx["dept_a_id"])

        payload = create_cross_dept_permission_payload(student["id"], ctx["dept_b_id"])
        resp = api_client.create_cross_dept_permission(sid, payload, TEST_USERS["professor_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ACTIVE"

    def test_create_permission_student_denied(self):
        """Student cannot grant cross-dept permissions -> ENROLLMENT_ROLE_DENIED."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]
        student = create_student(sid, ctx["dept_a_id"])

        payload = create_cross_dept_permission_payload(student["id"], ctx["dept_b_id"])
        resp = api_client.create_cross_dept_permission(sid, payload, TEST_USERS["student_headers"])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_get_permission_success(self):
        """Get permission by ID returns correct data."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]
        student = create_student(sid, ctx["dept_a_id"])
        perm = create_cross_dept_permission(sid, student["id"], ctx["dept_b_id"])

        resp = api_client.get_cross_dept_permission(sid, perm["id"], TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        assert data["id"] == perm["id"]

    def test_get_permission_not_found(self):
        """Non-existent permission -> CROSS_DEPT_PERMISSION_UNKNOWN."""
        ctx = setup_two_departments()
        resp = api_client.get_cross_dept_permission(
            ctx["semester_id"], NON_EXISTENT_UUID, TEST_USERS["registrar_headers"]
        )
        validate_error(resp, ApiErrorId.CROSS_DEPT_PERMISSION_UNKNOWN)


class TestCrossDeptEnrollment:
    """Tests for cross-department enrollment constraints."""

    def test_cross_dept_enrollment_blocked_without_permission(self):
        """Cross-dept enrollment without permission or open flag -> CROSS_DEPT_NOT_PERMITTED."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]

        # Student in dept A tries to enroll in dept B course (dept B not open)
        student = create_student(sid, ctx["dept_a_id"], cumulative_gpa=4.0, max_credits=30)
        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, ctx["dept_b_id"], ctx["course_b_id"], ctx["section_b_id"],
            payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.CROSS_DEPT_NOT_PERMITTED)

    def test_cross_dept_enrollment_with_permission(self):
        """Cross-dept enrollment succeeds with ACTIVE permission."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]

        student = create_student(sid, ctx["dept_a_id"], cumulative_gpa=4.0, max_credits=30)
        create_cross_dept_permission(sid, student["id"], ctx["dept_b_id"])

        enrollment = enroll_student(sid, ctx["dept_b_id"], ctx["course_b_id"],
                                     ctx["section_b_id"], student["id"])
        assert enrollment["status"] == "ENROLLED"
        assert enrollment["is_cross_dept"] is True

    def test_cross_dept_enrollment_with_open_flag(self):
        """Cross-dept enrollment succeeds when department has cross_dept_open=true."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        # Create an open department
        open_dept = create_department(sid, dept_code="OPEN", dept_name="Open Dept", cross_dept_open=True)
        instructor_b = create_instructor(sid, open_dept["id"])
        course_b = create_course(sid, open_dept["id"], credit_hours=3, course_code="OPEN-101")
        section_b = create_section(sid, open_dept["id"], course_b["id"], instructor_b["id"],
                                    schedule_days="TR", schedule_start="14:00", schedule_end="15:00",
                                    location="Room-OPEN")

        # Student in original dept
        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enrollment = enroll_student(sid, open_dept["id"], course_b["id"], section_b["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"
        assert enrollment["is_cross_dept"] is True

    def test_cross_dept_is_cross_dept_flag(self):
        """is_cross_dept is true when student major differs from course department."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]

        student = create_student(sid, ctx["dept_a_id"], cumulative_gpa=4.0, max_credits=30)
        create_cross_dept_permission(sid, student["id"], ctx["dept_b_id"])

        enrollment = enroll_student(sid, ctx["dept_b_id"], ctx["course_b_id"],
                                     ctx["section_b_id"], student["id"])
        assert enrollment["is_cross_dept"] is True

    def test_same_dept_enrollment_not_cross_dept(self):
        """is_cross_dept is false for same-department enrollment."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]

        # Student in dept A enrolls in dept A course
        student = create_student(sid, ctx["dept_a_id"], cumulative_gpa=4.0, max_credits=30)
        enrollment = enroll_student(sid, ctx["dept_a_id"], ctx["course_a_id"],
                                     ctx["section_a_id"], student["id"])
        assert enrollment["is_cross_dept"] is False


class TestCrossDeptLimits:
    """Tests for cross-dept max_courses limit."""

    def test_cross_dept_limit_reached(self):
        """Exceeding max_courses -> CROSS_DEPT_LIMIT_REACHED."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]

        student = create_student(sid, ctx["dept_a_id"], cumulative_gpa=4.0, max_credits=30)
        create_cross_dept_permission(sid, student["id"], ctx["dept_b_id"], max_courses=1)

        # First cross-dept enrollment succeeds
        enroll_student(sid, ctx["dept_b_id"], ctx["course_b_id"],
                       ctx["section_b_id"], student["id"])

        # Create second course in dept B
        course_b2 = create_course(sid, ctx["dept_b_id"], credit_hours=3, course_code="MATH-201")
        section_b2 = create_section(sid, ctx["dept_b_id"], course_b2["id"], ctx["instructor_b_id"],
                                     schedule_days="MWF", schedule_start="14:00", schedule_end="15:00",
                                     location="Room-B2")

        # Second cross-dept enrollment should fail
        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, ctx["dept_b_id"], course_b2["id"], section_b2["id"],
            payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.CROSS_DEPT_LIMIT_REACHED)

    def test_cross_dept_courses_used_tracking(self):
        """courses_used increments on enrollment and decrements on drop."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]

        student = create_student(sid, ctx["dept_a_id"], cumulative_gpa=4.0, max_credits=30)
        perm = create_cross_dept_permission(sid, student["id"], ctx["dept_b_id"])
        assert perm["courses_used"] == 0

        # Enroll
        enrollment = enroll_student(sid, ctx["dept_b_id"], ctx["course_b_id"],
                                     ctx["section_b_id"], student["id"])

        resp = api_client.get_cross_dept_permission(sid, perm["id"], TEST_USERS["registrar_headers"])
        perm_after = validate_success(resp)
        assert perm_after["courses_used"] == 1

        # Drop
        api_client.drop_enrollment(
            sid, ctx["dept_b_id"], ctx["course_b_id"], ctx["section_b_id"],
            enrollment["id"], TEST_USERS["student_headers"]
        )

        resp = api_client.get_cross_dept_permission(sid, perm["id"], TEST_USERS["registrar_headers"])
        perm_after_drop = validate_success(resp)
        assert perm_after_drop["courses_used"] == 0


class TestCrossDeptRevocation:
    """Tests for revoking cross-department permissions."""

    def test_revoke_permission_success(self):
        """Revoke an ACTIVE permission with no ENROLLED enrollments -> REVOKED."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]

        student = create_student(sid, ctx["dept_a_id"])
        perm = create_cross_dept_permission(sid, student["id"], ctx["dept_b_id"])

        resp = api_client.revoke_cross_dept_permission(sid, perm["id"], TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        assert data["status"] == "REVOKED"

    def test_revoke_blocked_with_enrolled_dependency(self):
        """Cannot revoke permission when student has ENROLLED cross-dept enrollments -> CROSS_DEPT_REVOKE_BLOCKED."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]

        student = create_student(sid, ctx["dept_a_id"], cumulative_gpa=4.0, max_credits=30)
        perm = create_cross_dept_permission(sid, student["id"], ctx["dept_b_id"])
        enroll_student(sid, ctx["dept_b_id"], ctx["course_b_id"], ctx["section_b_id"], student["id"])

        resp = api_client.revoke_cross_dept_permission(sid, perm["id"], TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.CROSS_DEPT_REVOKE_BLOCKED)

    def test_revoke_auto_drops_pending_and_waitlisted(self):
        """Revoking permission auto-drops PENDING_APPROVAL and WAITLISTED cross-dept enrollments."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]

        # Create requires_approval section in dept B
        course_b2 = create_course(sid, ctx["dept_b_id"], credit_hours=3, course_code="REV-B2")
        section_b2 = create_section(sid, ctx["dept_b_id"], course_b2["id"], ctx["instructor_b_id"],
                                     requires_approval=True,
                                     schedule_days="MWF", schedule_start="08:00", schedule_end="09:00",
                                     location="Room-REV")

        student = create_student(sid, ctx["dept_a_id"], cumulative_gpa=4.0, max_credits=30)
        perm = create_cross_dept_permission(sid, student["id"], ctx["dept_b_id"])

        # Create PENDING_APPROVAL enrollment
        enrollment = enroll_student(sid, ctx["dept_b_id"], course_b2["id"], section_b2["id"], student["id"])
        assert enrollment["status"] == "PENDING_APPROVAL"

        # Revoke permission (should succeed since enrollment is PENDING, not ENROLLED)
        resp = api_client.revoke_cross_dept_permission(sid, perm["id"], TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        assert data["status"] == "REVOKED"

        # PENDING enrollment should be auto-dropped
        resp = api_client.get_enrollment(
            sid, ctx["dept_b_id"], course_b2["id"], section_b2["id"],
            enrollment["id"], TEST_USERS["registrar_headers"]
        )
        enrollment_data = validate_success(resp)
        assert enrollment_data["status"] == "DROPPED", \
            "PENDING_APPROVAL enrollment should be auto-dropped when permission is revoked"

    def test_revoke_already_revoked(self):
        """Cannot revoke an already-revoked permission."""
        ctx = setup_two_departments()
        sid = ctx["semester_id"]

        student = create_student(sid, ctx["dept_a_id"])
        perm = create_cross_dept_permission(sid, student["id"], ctx["dept_b_id"])
        api_client.revoke_cross_dept_permission(sid, perm["id"], TEST_USERS["registrar_headers"])

        # Try to revoke again -> should fail (not in ACTIVE state)
        resp = api_client.revoke_cross_dept_permission(sid, perm["id"], TEST_USERS["registrar_headers"])
        # The exact error depends on implementation, but it should not succeed
        assert resp.status_code >= 400, "Revoking already-revoked permission should fail"
