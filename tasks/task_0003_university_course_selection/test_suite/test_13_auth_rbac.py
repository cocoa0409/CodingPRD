"""Tests for authentication, authorization, and RBAC permission matrix."""
import pytest
from test_helpers import (
    validate_error, api_client, ApiErrorId, TEST_USERS,
    create_semester_payload, create_department_payload,
    create_course_payload, create_enrollment_payload,
)
from test_helpers.fixtures import (
    create_semester, create_department, create_instructor, create_course, create_section,
    create_student, create_semester_in_open_enrollment, enroll_student,
    setup_enrollment_ready, setup_approval_required_scenario,
)
from prd_bench_local_runner.testing import build_user_headers


class TestMissingAuth:
    """Tests for ENROLLMENT_AUTH_MISSING when identity/role headers are missing."""

    def test_no_headers_at_all(self):
        """Request with no auth headers -> ENROLLMENT_AUTH_MISSING."""
        resp = api_client.list_semesters(headers={})
        validate_error(resp, ApiErrorId.ENROLLMENT_AUTH_MISSING)

    def test_missing_role_header(self):
        """Request with identity but no X-Caller-Role -> ENROLLMENT_AUTH_MISSING."""
        headers = {"X-Registrar-Id": "test-reg-1"}
        resp = api_client.list_semesters(headers=headers)
        validate_error(resp, ApiErrorId.ENROLLMENT_AUTH_MISSING)

    def test_missing_identity_header(self):
        """Request with role but no identity header -> ENROLLMENT_AUTH_MISSING."""
        headers = {"X-Caller-Role": "Registrar"}
        resp = api_client.list_semesters(headers=headers)
        validate_error(resp, ApiErrorId.ENROLLMENT_AUTH_MISSING)

    def test_invalid_role_value(self):
        """Request with unrecognized role -> ENROLLMENT_AUTH_MISSING."""
        headers = {"X-Registrar-Id": "test-reg-1", "X-Caller-Role": "InvalidRole"}
        resp = api_client.list_semesters(headers=headers)
        validate_error(resp, ApiErrorId.ENROLLMENT_AUTH_MISSING)


class TestRegistrarExclusiveOperations:
    """Tests that registrar-exclusive operations reject other roles."""

    @pytest.mark.parametrize("role_key", ["student_headers", "professor_headers"])
    def test_create_semester_registrar_only(self, role_key):
        """Only registrar can create semesters."""
        resp = api_client.create_semester(create_semester_payload(), TEST_USERS[role_key])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    @pytest.mark.parametrize("role_key", ["student_headers", "professor_headers"])
    def test_open_enrollment_registrar_only(self, role_key):
        """Only registrar can open enrollment."""
        semester = create_semester()
        resp = api_client.open_enrollment(semester["id"], TEST_USERS[role_key])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    @pytest.mark.parametrize("role_key", ["student_headers", "professor_headers"])
    def test_close_enrollment_registrar_only(self, role_key):
        """Only registrar can close enrollment."""
        semester, *_ = create_semester_in_open_enrollment()
        resp = api_client.close_enrollment(semester["id"], TEST_USERS[role_key])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    @pytest.mark.parametrize("role_key", ["student_headers", "professor_headers"])
    def test_finalize_registrar_only(self, role_key):
        """Only registrar can finalize semester."""
        semester = create_semester()
        resp = api_client.finalize_semester(semester["id"], TEST_USERS[role_key])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    @pytest.mark.parametrize("role_key", ["student_headers", "professor_headers"])
    def test_create_department_registrar_only(self, role_key):
        """Only registrar can create departments."""
        semester = create_semester()
        resp = api_client.create_department(semester["id"], create_department_payload(), TEST_USERS[role_key])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    @pytest.mark.parametrize("role_key", ["student_headers", "professor_headers"])
    def test_create_instructor_registrar_only(self, role_key):
        """Only registrar can register instructors."""
        semester = create_semester()
        dept = create_department(semester["id"])
        from test_helpers.factories import create_instructor_payload
        resp = api_client.create_instructor(semester["id"], create_instructor_payload(dept["id"]), TEST_USERS[role_key])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    @pytest.mark.parametrize("role_key", ["student_headers", "professor_headers"])
    def test_create_student_registrar_only(self, role_key):
        """Only registrar can register students."""
        semester = create_semester()
        dept = create_department(semester["id"])
        from test_helpers.factories import create_student_payload
        resp = api_client.create_student(semester["id"], create_student_payload(dept["id"]), TEST_USERS[role_key])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_update_student_registrar_only(self):
        """Only registrar can update student records."""
        semester = create_semester()
        dept = create_department(semester["id"])
        student = create_student(semester["id"], dept["id"])
        resp = api_client.update_student(
            semester["id"], student["id"],
            {"max_credits": 22}, TEST_USERS["professor_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_withdraw_registrar_only(self):
        """Only registrar can perform late withdrawal."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        resp = api_client.withdraw_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_schedule_conflicts_registrar_only(self):
        """Only registrar can view schedule conflicts."""
        semester, *_ = create_semester_in_open_enrollment()
        for role in ["student_headers", "professor_headers"]:
            resp = api_client.list_schedule_conflicts(semester["id"], TEST_USERS[role])
            validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_waitlist_promotions_registrar_only(self):
        """Only registrar can view waitlist promotions."""
        semester, *_ = create_semester_in_open_enrollment()
        for role in ["student_headers", "professor_headers"]:
            resp = api_client.list_waitlist_promotions(semester["id"], TEST_USERS[role])
            validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)


class TestProfessorExclusiveOperations:
    """Tests that professor-exclusive operations reject other roles."""

    def test_approve_professor_only(self):
        """Only professor can approve enrollment requests."""
        ctx = setup_approval_required_scenario()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        for role in ["student_headers", "registrar_headers"]:
            resp = api_client.approve_enrollment(
                ctx["semester_id"], ctx["department_id"], ctx["course_id"],
                ctx["section_id"], enrollment["id"], TEST_USERS[role]
            )
            validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_reject_professor_only(self):
        """Only professor can reject enrollment requests."""
        ctx = setup_approval_required_scenario()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        for role in ["student_headers", "registrar_headers"]:
            resp = api_client.reject_enrollment(
                ctx["semester_id"], ctx["department_id"], ctx["course_id"],
                ctx["section_id"], enrollment["id"], TEST_USERS[role]
            )
            validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)


class TestEnrollmentRolePermissions:
    """Tests for enrollment creation role permissions."""

    def test_student_can_enroll(self):
        """Student can create enrollment (shared with Registrar)."""
        ctx = setup_enrollment_ready()
        payload = create_enrollment_payload(ctx["student_id"])
        resp = api_client.create_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], payload, TEST_USERS["student_headers"]
        )
        # Should succeed (201)
        assert resp.status_code == 201

    def test_registrar_can_enroll(self):
        """Registrar can create enrollment on behalf of student."""
        ctx = setup_enrollment_ready()
        payload = create_enrollment_payload(ctx["student_id"])
        resp = api_client.create_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], payload, TEST_USERS["registrar_headers"]
        )
        assert resp.status_code == 201

    def test_professor_cannot_enroll(self):
        """Professor cannot create enrollments -> ENROLLMENT_ROLE_DENIED."""
        ctx = setup_enrollment_ready()
        payload = create_enrollment_payload(ctx["student_id"])
        resp = api_client.create_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], payload, TEST_USERS["professor_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)
