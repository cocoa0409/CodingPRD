"""Tests for Semester phase transitions (state machine)."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    create_semester, create_department, create_instructor, create_course, create_section,
    create_student, create_semester_in_open_enrollment, create_semester_in_closed_enrollment,
    enroll_student, setup_approval_required_scenario,
)


class TestOpenEnrollment:
    """Tests for PLANNING -> OPEN_ENROLLMENT transition."""

    def test_open_enrollment_success(self):
        """Open enrollment when dept+course+section exist -> phase=OPEN_ENROLLMENT."""
        semester = create_semester()
        sid = semester["id"]
        dept = create_department(sid)
        instructor = create_instructor(sid, dept["id"])
        course = create_course(sid, dept["id"])
        create_section(sid, dept["id"], course["id"], instructor["id"])

        resp = api_client.open_enrollment(sid, TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        assert data["phase"] == "OPEN_ENROLLMENT"

    def test_open_enrollment_no_department(self):
        """Open enrollment without any departments -> SEMESTER_PHASE_INVALID."""
        semester = create_semester()
        resp = api_client.open_enrollment(semester["id"], TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.SEMESTER_PHASE_INVALID)

    def test_open_enrollment_no_section(self):
        """Open enrollment with department and course but no section -> SEMESTER_PHASE_INVALID."""
        semester = create_semester()
        dept = create_department(semester["id"])
        create_course(semester["id"], dept["id"])
        resp = api_client.open_enrollment(semester["id"], TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.SEMESTER_PHASE_INVALID)

    def test_open_enrollment_wrong_phase(self):
        """Cannot open enrollment from OPEN_ENROLLMENT or FINALIZED -> SEMESTER_PHASE_INVALID."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        resp = api_client.open_enrollment(semester["id"], TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.SEMESTER_PHASE_INVALID)

    def test_open_enrollment_student_denied(self):
        """Student cannot open enrollment -> ENROLLMENT_ROLE_DENIED."""
        semester = create_semester()
        resp = api_client.open_enrollment(semester["id"], TEST_USERS["student_headers"])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_open_enrollment_professor_denied(self):
        """Professor cannot open enrollment -> ENROLLMENT_ROLE_DENIED."""
        semester = create_semester()
        resp = api_client.open_enrollment(semester["id"], TEST_USERS["professor_headers"])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)


class TestCloseEnrollment:
    """Tests for OPEN_ENROLLMENT -> CLOSED_ENROLLMENT transition."""

    def test_close_enrollment_success(self):
        """Close enrollment from OPEN_ENROLLMENT -> CLOSED_ENROLLMENT."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        resp = api_client.close_enrollment(semester["id"], TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        assert data["phase"] == "CLOSED_ENROLLMENT"

    def test_close_enrollment_auto_rejects_pending(self):
        """Closing enrollment auto-rejects all PENDING_APPROVAL enrollments."""
        ctx = setup_approval_required_scenario()
        sid = ctx["semester_id"]

        # Create a pending enrollment
        enrollment = enroll_student(sid, ctx["department_id"], ctx["course_id"],
                                     ctx["section_id"], ctx["student_id"])
        assert enrollment["status"] == "PENDING_APPROVAL"

        # Close enrollment
        api_client.close_enrollment(sid, TEST_USERS["registrar_headers"])

        # Check enrollment is now REJECTED
        resp = api_client.get_enrollment(
            sid, ctx["department_id"], ctx["course_id"], ctx["section_id"],
            enrollment["id"], TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "REJECTED", "PENDING_APPROVAL enrollment should be auto-rejected on close"

    def test_close_enrollment_auto_drops_waitlisted(self):
        """Closing enrollment auto-drops all WAITLISTED enrollments."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        # Fill section (capacity 30 by default) then add waitlisted student
        # Create section with capacity=1 instead for simplicity
        course2 = create_course(sid, dept["id"], credit_hours=3, course_code="WAIT-01")
        section2 = create_section(sid, dept["id"], course2["id"], instructor["id"], capacity=1, waitlist_cap=5)

        # Fill the single seat
        s1 = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], course2["id"], section2["id"], s1["id"])

        # Waitlist a second student
        s2 = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enrollment2 = enroll_student(sid, dept["id"], course2["id"], section2["id"], s2["id"])
        assert enrollment2["status"] == "WAITLISTED"

        # Close enrollment
        api_client.close_enrollment(sid, TEST_USERS["registrar_headers"])

        # Check waitlisted enrollment is now DROPPED
        resp = api_client.get_enrollment(
            sid, dept["id"], course2["id"], section2["id"],
            enrollment2["id"], TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "DROPPED", "WAITLISTED enrollment should be auto-dropped on close"

    def test_close_enrollment_wrong_phase(self):
        """Cannot close enrollment from PLANNING -> SEMESTER_PHASE_INVALID."""
        semester = create_semester()
        resp = api_client.close_enrollment(semester["id"], TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.SEMESTER_PHASE_INVALID)


class TestReopenEnrollment:
    """Tests for CLOSED_ENROLLMENT -> OPEN_ENROLLMENT transition."""

    def test_reopen_enrollment_success(self):
        """Registrar can reopen enrollment from CLOSED_ENROLLMENT."""
        semester, dept, course, section, instructor = create_semester_in_closed_enrollment()
        resp = api_client.reopen_enrollment(semester["id"], TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        assert data["phase"] == "OPEN_ENROLLMENT"

    def test_reopen_enrollment_wrong_phase(self):
        """Cannot reopen from PLANNING or FINALIZED -> SEMESTER_PHASE_INVALID."""
        semester = create_semester()
        resp = api_client.reopen_enrollment(semester["id"], TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.SEMESTER_PHASE_INVALID)


class TestFinalizeSemester:
    """Tests for CLOSED_ENROLLMENT -> FINALIZED transition."""

    def test_finalize_success(self):
        """Finalize from CLOSED_ENROLLMENT when no PENDING_APPROVAL remain."""
        semester, dept, course, section, instructor = create_semester_in_closed_enrollment()
        resp = api_client.finalize_semester(semester["id"], TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        assert data["phase"] == "FINALIZED"

    def test_finalize_wrong_phase(self):
        """Cannot finalize from PLANNING or OPEN_ENROLLMENT -> SEMESTER_PHASE_INVALID."""
        semester = create_semester()
        resp = api_client.finalize_semester(semester["id"], TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.SEMESTER_PHASE_INVALID)

    def test_finalize_from_open_enrollment(self):
        """Cannot finalize directly from OPEN_ENROLLMENT -> SEMESTER_PHASE_INVALID."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        resp = api_client.finalize_semester(semester["id"], TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.SEMESTER_PHASE_INVALID)


class TestInvalidPhaseTransitions:
    """Parametrized tests for invalid semester phase transitions."""

    @pytest.mark.parametrize("action_name,action_fn", [
        ("open_enrollment", lambda api, sid, h: api.open_enrollment(sid, h)),
        ("close_enrollment", lambda api, sid, h: api.close_enrollment(sid, h)),
        ("reopen_enrollment", lambda api, sid, h: api.reopen_enrollment(sid, h)),
        ("finalize", lambda api, sid, h: api.finalize_semester(sid, h)),
    ])
    def test_phase_transition_on_finalized_semester(self, action_name, action_fn):
        """No phase transition is possible from FINALIZED -> SEMESTER_PHASE_INVALID."""
        semester, dept, course, section, instructor = create_semester_in_closed_enrollment()
        api_client.finalize_semester(semester["id"], TEST_USERS["registrar_headers"])
        resp = action_fn(api_client, semester["id"], TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.SEMESTER_PHASE_INVALID)
