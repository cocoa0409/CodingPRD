"""Tests for credit load computation, GPA thresholds, and academic standing constraints."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    create_enrollment_payload, create_course_payload,
    DEFAULT_MAX_CREDITS, PROBATION_MAX_CREDITS, HONORS_MAX_CREDITS,
)
from test_helpers.fixtures import (
    create_semester_in_open_enrollment, create_student, create_course, create_section,
    enroll_student, setup_enrollment_ready,
)


class TestCreditLimitEnforcement:
    """Tests for credit limit exceeded during enrollment."""

    def test_credit_limit_exceeded(self):
        """Enrolling beyond max_credits triggers CREDIT_LIMIT_EXCEEDED."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        # Student with max_credits=6
        student = create_student(sid, dept["id"], max_credits=6, cumulative_gpa=4.0)

        # Course with 4 credit hours
        c1 = create_course(sid, dept["id"], credit_hours=4, course_code="CR-01")
        s1 = create_section(sid, dept["id"], c1["id"], instructor["id"],
                             schedule_days="MWF", schedule_start="08:00", schedule_end="09:00",
                             location="Room-1")
        enroll_student(sid, dept["id"], c1["id"], s1["id"], student["id"])

        # Another course with 3 credit hours (total would be 7, exceeding 6)
        c2 = create_course(sid, dept["id"], credit_hours=3, course_code="CR-02")
        s2 = create_section(sid, dept["id"], c2["id"], instructor["id"],
                             schedule_days="TR", schedule_start="10:00", schedule_end="11:00",
                             location="Room-2")
        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], c2["id"], s2["id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.CREDIT_LIMIT_EXCEEDED)

    def test_credit_limit_exact_boundary(self):
        """Enrolling exactly at max_credits succeeds (boundary test)."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        student = create_student(sid, dept["id"], max_credits=6, cumulative_gpa=4.0)

        c1 = create_course(sid, dept["id"], credit_hours=3, course_code="EX-01")
        s1 = create_section(sid, dept["id"], c1["id"], instructor["id"],
                             schedule_days="MWF", schedule_start="08:00", schedule_end="09:00",
                             location="Room-E1")
        enroll_student(sid, dept["id"], c1["id"], s1["id"], student["id"])

        # Exactly 6 credits (3+3)
        c2 = create_course(sid, dept["id"], credit_hours=3, course_code="EX-02")
        s2 = create_section(sid, dept["id"], c2["id"], instructor["id"],
                             schedule_days="TR", schedule_start="10:00", schedule_end="11:00",
                             location="Room-E2")
        enrollment = enroll_student(sid, dept["id"], c2["id"], s2["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"

        # Verify credits_enrolled = 6
        resp = api_client.get_student(sid, student["id"], TEST_USERS["registrar_headers"])
        student_data = validate_success(resp)
        assert student_data["credits_enrolled"] == 6
        assert student_data["credits_available"] == 0

    def test_credit_limit_one_over_boundary(self):
        """Enrolling one credit over max_credits fails (boundary test)."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        student = create_student(sid, dept["id"], max_credits=5, cumulative_gpa=4.0)

        c1 = create_course(sid, dept["id"], credit_hours=3, course_code="OV-01")
        s1 = create_section(sid, dept["id"], c1["id"], instructor["id"],
                             schedule_days="MWF", schedule_start="08:00", schedule_end="09:00",
                             location="Room-OV1")
        enroll_student(sid, dept["id"], c1["id"], s1["id"], student["id"])

        # Would be 6 credits, max is 5
        c2 = create_course(sid, dept["id"], credit_hours=3, course_code="OV-02")
        s2 = create_section(sid, dept["id"], c2["id"], instructor["id"],
                             schedule_days="TR", schedule_start="10:00", schedule_end="11:00",
                             location="Room-OV2")
        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], c2["id"], s2["id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.CREDIT_LIMIT_EXCEEDED)


class TestProbationCreditCap:
    """Tests for probation credit limit cap of 12."""

    def test_probation_caps_at_12(self):
        """Student on PROBATION capped at 12 credits regardless of max_credits."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        # Student on probation with max_credits=18 (should be capped at 12)
        student = create_student(sid, dept["id"],
                                  academic_standing="PROBATION",
                                  max_credits=18,
                                  cumulative_gpa=2.0)

        # Enroll in 12 credits (4 courses * 3 credits)
        for i in range(4):
            c = create_course(sid, dept["id"], credit_hours=3, course_code=f"PROB-{i}")
            days = "MWF" if i % 2 == 0 else "TR"
            start = f"{8 + i * 2:02d}:00"
            end = f"{9 + i * 2:02d}:00"
            s = create_section(sid, dept["id"], c["id"], instructor["id"],
                                schedule_days=days, schedule_start=start, schedule_end=end,
                                location=f"Room-P{i}")
            enroll_student(sid, dept["id"], c["id"], s["id"], student["id"])

        # Verify 12 credits enrolled
        resp = api_client.get_student(sid, student["id"], TEST_USERS["registrar_headers"])
        student_data = validate_success(resp)
        assert student_data["credits_enrolled"] == 12

        # Try to enroll in one more (13th credit) -> CREDIT_LIMIT_EXCEEDED
        c_extra = create_course(sid, dept["id"], credit_hours=1, course_code="PROB-EX")
        s_extra = create_section(sid, dept["id"], c_extra["id"], instructor["id"],
                                  schedule_days="MWF", schedule_start="18:00", schedule_end="19:00",
                                  location="Room-PX")
        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], c_extra["id"], s_extra["id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.CREDIT_LIMIT_EXCEEDED)

    def test_probation_boundary_exact_12(self):
        """Student on PROBATION can enroll up to exactly 12 credits."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        student = create_student(sid, dept["id"],
                                  academic_standing="PROBATION",
                                  max_credits=18,
                                  cumulative_gpa=2.0)

        # Enroll in 9 credits
        for i in range(3):
            c = create_course(sid, dept["id"], credit_hours=3, course_code=f"PBD-{i}")
            days = "MWF" if i % 2 == 0 else "TR"
            start = f"{8 + i * 2:02d}:00"
            end = f"{9 + i * 2:02d}:00"
            s = create_section(sid, dept["id"], c["id"], instructor["id"],
                                schedule_days=days, schedule_start=start, schedule_end=end,
                                location=f"Room-PBD{i}")
            enroll_student(sid, dept["id"], c["id"], s["id"], student["id"])

        # 12th credit exactly
        c12 = create_course(sid, dept["id"], credit_hours=3, course_code="PBD-12")
        s12 = create_section(sid, dept["id"], c12["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="16:00", schedule_end="17:00",
                              location="Room-PBD12")
        enrollment = enroll_student(sid, dept["id"], c12["id"], s12["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"


class TestHonorsOverride:
    """Tests for registrar honor overrides allowing up to 22 credits."""

    def test_honors_override_allows_more_credits(self):
        """Registrar can set max_credits to 22 for honors students."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        student = create_student(sid, dept["id"], cumulative_gpa=4.0)
        # Override max_credits to 22
        api_client.update_student(
            sid, student["id"],
            {"max_credits": 22}, TEST_USERS["registrar_headers"]
        )

        # Enroll in 21 credits (7 courses * 3)
        for i in range(7):
            c = create_course(sid, dept["id"], credit_hours=3, course_code=f"HON-{i}")
            days = "MWF" if i % 2 == 0 else "TR"
            start = f"{7 + i:02d}:00"
            end = f"{8 + i:02d}:00"
            s = create_section(sid, dept["id"], c["id"], instructor["id"],
                                schedule_days=days, schedule_start=start, schedule_end=end,
                                location=f"Room-HON{i}")
            enroll_student(sid, dept["id"], c["id"], s["id"], student["id"])

        resp = api_client.get_student(sid, student["id"], TEST_USERS["registrar_headers"])
        student_data = validate_success(resp)
        assert student_data["credits_enrolled"] == 21
        assert student_data["credits_available"] == 1


class TestGPAThreshold:
    """Tests for GPA minimum enforcement."""

    def test_gpa_below_minimum(self):
        """Student with GPA below course min_gpa -> GPA_BELOW_MINIMUM."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        # Course requiring 3.5 GPA
        high_course = create_course(sid, dept["id"], credit_hours=3, course_code="HG-301", min_gpa=3.5)
        high_section = create_section(sid, dept["id"], high_course["id"], instructor["id"],
                                       schedule_days="TR", schedule_start="14:00", schedule_end="15:00",
                                       location="Room-HG")

        # Student with 3.0 GPA (below 3.5)
        student = create_student(sid, dept["id"], cumulative_gpa=3.0)
        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], high_course["id"], high_section["id"],
            payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.GPA_BELOW_MINIMUM)

    def test_gpa_at_minimum_succeeds(self):
        """Student with GPA exactly at course min_gpa can enroll (boundary)."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        high_course = create_course(sid, dept["id"], credit_hours=3, course_code="GM-301", min_gpa=3.5)
        high_section = create_section(sid, dept["id"], high_course["id"], instructor["id"],
                                       schedule_days="TR", schedule_start="14:00", schedule_end="15:00",
                                       location="Room-GM")

        student = create_student(sid, dept["id"], cumulative_gpa=3.5)
        enrollment = enroll_student(sid, dept["id"], high_course["id"], high_section["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"

    def test_gpa_above_minimum_succeeds(self):
        """Student with GPA above course min_gpa can enroll."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        high_course = create_course(sid, dept["id"], credit_hours=3, course_code="GA-301", min_gpa=3.0)
        high_section = create_section(sid, dept["id"], high_course["id"], instructor["id"],
                                       schedule_days="TR", schedule_start="14:00", schedule_end="15:00",
                                       location="Room-GA")

        student = create_student(sid, dept["id"], cumulative_gpa=3.8)
        enrollment = enroll_student(sid, dept["id"], high_course["id"], high_section["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"

    def test_gpa_just_below_minimum_fails(self):
        """Student with GPA 0.01 below min_gpa -> GPA_BELOW_MINIMUM (precision boundary)."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        high_course = create_course(sid, dept["id"], credit_hours=3, course_code="GJ-301", min_gpa=3.5)
        high_section = create_section(sid, dept["id"], high_course["id"], instructor["id"],
                                       schedule_days="TR", schedule_start="14:00", schedule_end="15:00",
                                       location="Room-GJ")

        student = create_student(sid, dept["id"], cumulative_gpa=3.49)
        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], high_course["id"], high_section["id"],
            payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.GPA_BELOW_MINIMUM)


class TestCreditLoadComputation:
    """Tests for credits_enrolled and credits_available derived fields."""

    def test_credits_include_pending_approval(self):
        """credits_enrolled includes PENDING_APPROVAL enrollments (reserved credits)."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        # Create requires_approval section
        c = create_course(sid, dept["id"], credit_hours=4, course_code="PEND-CR")
        s = create_section(sid, dept["id"], c["id"], instructor["id"],
                            requires_approval=True,
                            schedule_days="MWF", schedule_start="08:00", schedule_end="09:00",
                            location="Room-PC")

        student = create_student(sid, dept["id"], cumulative_gpa=4.0)
        enroll_student(sid, dept["id"], c["id"], s["id"], student["id"])

        resp = api_client.get_student(sid, student["id"], TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        assert data["credits_enrolled"] == 4, \
            "PENDING_APPROVAL enrollment should reserve credits"
        assert data["credits_available"] == data["max_credits"] - 4

    def test_credits_after_drop_decrease(self):
        """credits_enrolled decreases after dropping a course."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )

        api_client.drop_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["student_headers"]
        )

        resp = api_client.get_student(ctx["semester_id"], ctx["student_id"], TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        assert data["credits_enrolled"] == 0
        assert data["credits_available"] == data["max_credits"]
