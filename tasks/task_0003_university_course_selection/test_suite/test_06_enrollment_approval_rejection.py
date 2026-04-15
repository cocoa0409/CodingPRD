"""Tests for enrollment approval and rejection workflows."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    assert_enrollment,
    create_enrollment_payload,
)
from test_helpers.fixtures import (
    setup_approval_required_scenario, setup_enrollment_ready, create_student, create_course, create_section,
    enroll_student, create_semester_in_open_enrollment,
)


class TestApproveEnrollment:
    """Tests for POST .../enrollments/{id}/approve."""

    def test_approve_enrollment_to_enrolled(self):
        """Professor approves PENDING_APPROVAL -> ENROLLED when seats available."""
        ctx = setup_approval_required_scenario()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        assert enrollment["status"] == "PENDING_APPROVAL"

        resp = api_client.approve_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["professor_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "ENROLLED"

    def test_approve_updates_section_counters(self):
        """Approval increments seats_enrolled, decrements seats_available."""
        ctx = setup_approval_required_scenario()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )

        # Get section before approval
        resp = api_client.get_section(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], TEST_USERS["registrar_headers"]
        )
        before = validate_success(resp)

        api_client.approve_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["professor_headers"]
        )

        resp = api_client.get_section(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], TEST_USERS["registrar_headers"]
        )
        after = validate_success(resp)
        assert after["seats_enrolled"] == before["seats_enrolled"] + 1
        assert after["seats_available"] == before["seats_available"] - 1

    def test_approve_when_section_full_waitlists(self):
        """Approval when section full places student on waitlist instead."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        # Create a 1-capacity requires_approval section
        course2 = create_course(sid, dept["id"], credit_hours=3, course_code="APR-WL")
        section2 = create_section(
            sid, dept["id"], course2["id"], instructor["id"],
            capacity=1, waitlist_cap=5, requires_approval=True,
        )

        # Student A enrolls and gets approved (fills the seat)
        sa = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        ea = enroll_student(sid, dept["id"], course2["id"], section2["id"], sa["id"])
        api_client.approve_enrollment(
            sid, dept["id"], course2["id"], section2["id"],
            ea["id"], TEST_USERS["professor_headers"]
        )

        # Student B enrolls (PENDING_APPROVAL)
        sb = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        eb = enroll_student(sid, dept["id"], course2["id"], section2["id"], sb["id"])
        assert eb["status"] == "PENDING_APPROVAL"

        # Approve B -> should go to WAITLISTED since section is full
        resp = api_client.approve_enrollment(
            sid, dept["id"], course2["id"], section2["id"],
            eb["id"], TEST_USERS["professor_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "WAITLISTED", \
            "Approval when section is full should waitlist the student"
        assert data["waitlist_position"] == 1

    def test_approve_with_note(self):
        """Approval can include an approval_note."""
        ctx = setup_approval_required_scenario()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        resp = api_client.approve_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["professor_headers"],
            payload={"approval_note": "Welcome to the course"}
        )
        data = validate_success(resp)
        assert data["approval_note"] == "Welcome to the course"

    def test_approve_wrong_status(self):
        """Cannot approve enrollment that is not PENDING_APPROVAL -> ENROLLMENT_STATE_INVALID."""
        ctx = setup_enrollment_ready()
        # Direct enrollment (no approval required) -> status=ENROLLED
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        assert enrollment["status"] == "ENROLLED"

        resp = api_client.approve_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["professor_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_STATE_INVALID)

    def test_approve_student_denied(self):
        """Student cannot approve enrollments -> ENROLLMENT_ROLE_DENIED."""
        ctx = setup_approval_required_scenario()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        resp = api_client.approve_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_approve_registrar_denied(self):
        """Registrar cannot approve enrollments (professor exclusive) -> ENROLLMENT_ROLE_DENIED."""
        ctx = setup_approval_required_scenario()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        resp = api_client.approve_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["registrar_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)


class TestRejectEnrollment:
    """Tests for POST .../enrollments/{id}/reject."""

    def test_reject_enrollment_success(self):
        """Professor rejects PENDING_APPROVAL -> REJECTED."""
        ctx = setup_approval_required_scenario()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )

        resp = api_client.reject_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["professor_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "REJECTED"

    def test_reject_releases_credits(self):
        """Rejection releases the reserved credits from the student's load."""
        ctx = setup_approval_required_scenario()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )

        # Credits should be reserved
        resp = api_client.get_student(ctx["semester_id"], ctx["student_id"], TEST_USERS["registrar_headers"])
        before = validate_success(resp)
        assert before["credits_enrolled"] == ctx["course"]["credit_hours"]

        # Reject
        api_client.reject_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["professor_headers"]
        )

        resp = api_client.get_student(ctx["semester_id"], ctx["student_id"], TEST_USERS["registrar_headers"])
        after = validate_success(resp)
        assert after["credits_enrolled"] == 0, \
            "Credits should be released after rejection"
        assert after["credits_available"] == after["max_credits"]

    def test_reject_with_note(self):
        """Rejection can include an approval_note."""
        ctx = setup_approval_required_scenario()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        resp = api_client.reject_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["professor_headers"],
            payload={"approval_note": "Class is full, try next semester"}
        )
        data = validate_success(resp)
        assert data["approval_note"] == "Class is full, try next semester"

    def test_reject_wrong_status(self):
        """Cannot reject enrollment that is not PENDING_APPROVAL -> ENROLLMENT_STATE_INVALID."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        resp = api_client.reject_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["professor_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_STATE_INVALID)

    def test_reject_student_denied(self):
        """Student cannot reject enrollments -> ENROLLMENT_ROLE_DENIED."""
        ctx = setup_approval_required_scenario()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        resp = api_client.reject_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)
