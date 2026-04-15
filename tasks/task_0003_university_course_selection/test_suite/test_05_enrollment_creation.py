"""Tests for enrollment creation — the core enrollment request flow."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID,
    api_client, ApiErrorId, TEST_USERS,
    assert_enrollment,
    create_enrollment_payload, create_student_payload,
)
from test_helpers.fixtures import (
    setup_enrollment_ready, create_student, create_course, create_section,
    create_semester, create_department, create_instructor,
    create_semester_in_open_enrollment, enroll_student,
    setup_approval_required_scenario,
)


class TestEnrollmentDirectEnrollment:
    """Tests for direct enrollment (no approval required, seats available)."""

    def test_enroll_student_success(self):
        """Student enrolls in open section -> ENROLLED, 201."""
        ctx = setup_enrollment_ready()
        payload = create_enrollment_payload(ctx["student_id"])
        resp = api_client.create_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], payload, TEST_USERS["student_headers"]
        )
        data = validate_success(resp, expected_status=201)
        assert_enrollment(data)
        assert data["status"] == "ENROLLED"
        assert data["student_id"] == ctx["student_id"]
        assert data["section_id"] == ctx["section_id"]
        assert data["is_cross_dept"] is False, "Same-department enrollment should not be cross-dept"

    def test_enroll_updates_section_counters(self):
        """After enrollment, section.seats_enrolled increments, seats_available decrements."""
        ctx = setup_enrollment_ready()
        section_before = ctx["section"]
        enroll_student(ctx["semester_id"], ctx["department_id"], ctx["course_id"],
                       ctx["section_id"], ctx["student_id"])

        resp = api_client.get_section(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], TEST_USERS["registrar_headers"]
        )
        section_after = validate_success(resp)
        assert section_after["seats_enrolled"] == section_before["seats_enrolled"] + 1
        assert section_after["seats_available"] == section_before["seats_available"] - 1

    def test_enroll_updates_student_credits(self):
        """After enrollment, student.credits_enrolled increases by course.credit_hours."""
        ctx = setup_enrollment_ready()
        student_before = ctx["student"]
        credit_hours = ctx["course"]["credit_hours"]

        enroll_student(ctx["semester_id"], ctx["department_id"], ctx["course_id"],
                       ctx["section_id"], ctx["student_id"])

        resp = api_client.get_student(ctx["semester_id"], ctx["student_id"], TEST_USERS["registrar_headers"])
        student_after = validate_success(resp)
        assert student_after["credits_enrolled"] == student_before["credits_enrolled"] + credit_hours
        assert student_after["credits_available"] == student_after["max_credits"] - student_after["credits_enrolled"]

    def test_enroll_registrar_on_behalf(self):
        """Registrar can enroll a student on their behalf."""
        ctx = setup_enrollment_ready()
        payload = create_enrollment_payload(ctx["student_id"])
        resp = api_client.create_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], payload, TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ENROLLED"


class TestEnrollmentPendingApproval:
    """Tests for enrollment in requires_approval sections."""

    def test_enroll_requires_approval_pending(self):
        """Enrollment in requires_approval section -> PENDING_APPROVAL, credits reserved."""
        ctx = setup_approval_required_scenario()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        assert enrollment["status"] == "PENDING_APPROVAL"

        # Credits should be reserved
        resp = api_client.get_student(ctx["semester_id"], ctx["student_id"], TEST_USERS["registrar_headers"])
        student = validate_success(resp)
        assert student["credits_enrolled"] == ctx["course"]["credit_hours"], \
            "Credits should be reserved for PENDING_APPROVAL enrollment"


class TestEnrollmentWaitlist:
    """Tests for enrollment when section is full -> waitlist."""

    def test_enroll_waitlisted_when_section_full(self):
        """When section is full but waitlist has room -> WAITLISTED."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        # Create a 1-capacity section
        course2 = create_course(sid, dept["id"], credit_hours=3, course_code="WL-01")
        section2 = create_section(sid, dept["id"], course2["id"], instructor["id"],
                                   capacity=1, waitlist_cap=5)

        # Fill the seat
        s1 = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        e1 = enroll_student(sid, dept["id"], course2["id"], section2["id"], s1["id"])
        assert e1["status"] == "ENROLLED"

        # Second student should be waitlisted
        s2 = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        e2 = enroll_student(sid, dept["id"], course2["id"], section2["id"], s2["id"])
        assert e2["status"] == "WAITLISTED"
        assert e2["waitlist_position"] == 1, "First waitlisted student should have position 1"

    def test_waitlist_position_increments(self):
        """Multiple waitlisted students get incrementing positions."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        course2 = create_course(sid, dept["id"], credit_hours=3, course_code="WLP-01")
        section2 = create_section(sid, dept["id"], course2["id"], instructor["id"],
                                   capacity=1, waitlist_cap=5)

        # Fill the seat
        s1 = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], course2["id"], section2["id"], s1["id"])

        # Waitlist 3 students
        for expected_pos in [1, 2, 3]:
            s = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
            e = enroll_student(sid, dept["id"], course2["id"], section2["id"], s["id"])
            assert e["status"] == "WAITLISTED"
            assert e["waitlist_position"] == expected_pos, \
                f"Expected waitlist_position {expected_pos}, got {e['waitlist_position']}"

    def test_section_full_and_waitlist_full(self):
        """When section full and waitlist at cap -> SECTION_FULL."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        course2 = create_course(sid, dept["id"], credit_hours=3, course_code="SF-01")
        section2 = create_section(sid, dept["id"], course2["id"], instructor["id"],
                                   capacity=1, waitlist_cap=1)

        # Fill the seat
        s1 = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], course2["id"], section2["id"], s1["id"])

        # Fill the waitlist
        s2 = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        e2 = enroll_student(sid, dept["id"], course2["id"], section2["id"], s2["id"])
        assert e2["status"] == "WAITLISTED"

        # Third student -> SECTION_FULL (both section and waitlist are full)
        s3 = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        payload = create_enrollment_payload(s3["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], course2["id"], section2["id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.SECTION_FULL)

    def test_section_waitlist_count_updated(self):
        """Section waitlist_count reflects number of WAITLISTED enrollments."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        course2 = create_course(sid, dept["id"], credit_hours=3, course_code="WLC-01")
        section2 = create_section(sid, dept["id"], course2["id"], instructor["id"],
                                   capacity=1, waitlist_cap=10)

        # Fill the seat
        s1 = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], course2["id"], section2["id"], s1["id"])

        # Add 3 to waitlist
        for _ in range(3):
            s = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
            enroll_student(sid, dept["id"], course2["id"], section2["id"], s["id"])

        resp = api_client.get_section(
            sid, dept["id"], course2["id"], section2["id"], TEST_USERS["registrar_headers"]
        )
        section_data = validate_success(resp)
        assert section_data["waitlist_count"] == 3
        assert section_data["seats_enrolled"] == 1
        assert section_data["seats_available"] == 0


class TestEnrollmentValidationCascade:
    """Tests for the strict priority validation cascade on enrollment creation."""

    def test_registration_not_open(self):
        """Enrollment in PLANNING phase -> REGISTRATION_NOT_OPEN."""
        semester = create_semester()
        sid = semester["id"]
        dept = create_department(sid)
        instructor = create_instructor(sid, dept["id"])
        course = create_course(sid, dept["id"])
        section = create_section(sid, dept["id"], course["id"], instructor["id"])
        student = create_student(sid, dept["id"])

        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], course["id"], section["id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.REGISTRATION_NOT_OPEN)

    def test_student_suspended(self):
        """Suspended student cannot enroll -> STUDENT_SUSPENDED."""
        ctx = setup_enrollment_ready()
        sid = ctx["semester_id"]

        student = create_student(sid, ctx["department_id"], academic_standing="SUSPENDED", cumulative_gpa=3.0)
        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, ctx["department_id"], ctx["course_id"], ctx["section_id"],
            payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.STUDENT_SUSPENDED)

    def test_student_unknown(self):
        """Enrollment with non-existent student_id -> STUDENT_UNKNOWN."""
        ctx = setup_enrollment_ready()
        payload = create_enrollment_payload(NON_EXISTENT_UUID)
        resp = api_client.create_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.STUDENT_UNKNOWN)

    def test_duplicate_course_enrollment(self):
        """Student already enrolled in a section of the same course -> DUPLICATE_COURSE_ENROLLMENT."""
        ctx = setup_enrollment_ready()
        sid = ctx["semester_id"]

        # Enroll in first section
        enroll_student(sid, ctx["department_id"], ctx["course_id"], ctx["section_id"], ctx["student_id"])

        # Create second section of same course
        section2 = create_section(
            sid, ctx["department_id"], ctx["course_id"], ctx["instructor_id"],
            schedule_days="TR", schedule_start="14:00", schedule_end="15:00",
            location="Room-B",
        )

        # Try to enroll in second section of same course
        payload = create_enrollment_payload(ctx["student_id"])
        resp = api_client.create_enrollment(
            sid, ctx["department_id"], ctx["course_id"], section2["id"],
            payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.DUPLICATE_COURSE_ENROLLMENT)

    def test_professor_cannot_enroll(self):
        """Professor cannot create enrollments -> ENROLLMENT_ROLE_DENIED."""
        ctx = setup_enrollment_ready()
        payload = create_enrollment_payload(ctx["student_id"])
        resp = api_client.create_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], payload, TEST_USERS["professor_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_enrollment_path_validation_semester_unknown(self):
        """Enrollment with non-existent semester -> SEMESTER_UNKNOWN."""
        ctx = setup_enrollment_ready()
        payload = create_enrollment_payload(ctx["student_id"])
        resp = api_client.create_enrollment(
            NON_EXISTENT_UUID, ctx["department_id"], ctx["course_id"],
            ctx["section_id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.SEMESTER_UNKNOWN)

    def test_enrollment_path_validation_department_unknown(self):
        """Enrollment with non-existent department -> DEPARTMENT_UNKNOWN."""
        ctx = setup_enrollment_ready()
        payload = create_enrollment_payload(ctx["student_id"])
        resp = api_client.create_enrollment(
            ctx["semester_id"], NON_EXISTENT_UUID, ctx["course_id"],
            ctx["section_id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.DEPARTMENT_UNKNOWN)

    def test_enrollment_path_validation_course_unknown(self):
        """Enrollment with non-existent course -> COURSE_UNKNOWN."""
        ctx = setup_enrollment_ready()
        payload = create_enrollment_payload(ctx["student_id"])
        resp = api_client.create_enrollment(
            ctx["semester_id"], ctx["department_id"], NON_EXISTENT_UUID,
            ctx["section_id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.COURSE_UNKNOWN)

    def test_enrollment_path_validation_section_unknown(self):
        """Enrollment with non-existent section -> SECTION_UNKNOWN."""
        ctx = setup_enrollment_ready()
        payload = create_enrollment_payload(ctx["student_id"])
        resp = api_client.create_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            NON_EXISTENT_UUID, payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.SECTION_UNKNOWN)
