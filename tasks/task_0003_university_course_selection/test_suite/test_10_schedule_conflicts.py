"""Tests for schedule conflict detection including time overlap and travel buffer."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    create_enrollment_payload,
)
from test_helpers.fixtures import (
    create_semester_in_open_enrollment, create_student, create_course, create_section,
    enroll_student,
)


class TestScheduleOverlapDetection:
    """Tests for time-based conflict detection (PRD section 2.10)."""

    def test_overlapping_sections_same_days(self):
        """Sections on same days with overlapping time -> SCHEDULE_CONFLICT."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        # Course A: MWF 09:00-10:00
        c_a = create_course(sid, dept["id"], credit_hours=3, course_code="OVL-A")
        s_a = create_section(sid, dept["id"], c_a["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="09:00", schedule_end="10:00",
                              location="Room-A")

        # Course B: MWF 09:30-10:30 (overlaps with A by 30 minutes)
        c_b = create_course(sid, dept["id"], credit_hours=3, course_code="OVL-B")
        s_b = create_section(sid, dept["id"], c_b["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="09:30", schedule_end="10:30",
                              location="Room-A")

        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], c_a["id"], s_a["id"], student["id"])

        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], c_b["id"], s_b["id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.SCHEDULE_CONFLICT)

    def test_one_minute_overlap_is_conflict(self):
        """Even 1 minute of overlap constitutes a conflict (PRD: 'Even a single minute')."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        # Course A: MWF 09:00-10:00
        c_a = create_course(sid, dept["id"], credit_hours=3, course_code="1MIN-A")
        s_a = create_section(sid, dept["id"], c_a["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="09:00", schedule_end="10:00",
                              location="Room-1M")

        # Course B: MWF 09:59-11:00 (1-minute overlap from 09:59 to 10:00)
        c_b = create_course(sid, dept["id"], credit_hours=3, course_code="1MIN-B")
        s_b = create_section(sid, dept["id"], c_b["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="09:59", schedule_end="11:00",
                              location="Room-1M")

        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], c_a["id"], s_a["id"], student["id"])

        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], c_b["id"], s_b["id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.SCHEDULE_CONFLICT)

    def test_no_overlap_adjacent_sections(self):
        """Sections ending at 10:00 and starting at 10:00 in same location do not overlap."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        c_a = create_course(sid, dept["id"], credit_hours=3, course_code="ADJ-A")
        s_a = create_section(sid, dept["id"], c_a["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="09:00", schedule_end="10:00",
                              location="Room-ADJ")

        # Starts exactly when A ends (same location) -> no overlap
        c_b = create_course(sid, dept["id"], credit_hours=3, course_code="ADJ-B")
        s_b = create_section(sid, dept["id"], c_b["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="10:00", schedule_end="11:00",
                              location="Room-ADJ")

        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], c_a["id"], s_a["id"], student["id"])
        enrollment = enroll_student(sid, dept["id"], c_b["id"], s_b["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"

    def test_no_overlap_different_days(self):
        """Sections on non-overlapping days don't conflict even if times overlap."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        c_a = create_course(sid, dept["id"], credit_hours=3, course_code="DAY-A")
        s_a = create_section(sid, dept["id"], c_a["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="09:00", schedule_end="10:00",
                              location="Room-DY")

        # Same time but TR days -> no overlap
        c_b = create_course(sid, dept["id"], credit_hours=3, course_code="DAY-B")
        s_b = create_section(sid, dept["id"], c_b["id"], instructor["id"],
                              schedule_days="TR", schedule_start="09:00", schedule_end="10:00",
                              location="Room-DY")

        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], c_a["id"], s_a["id"], student["id"])
        enrollment = enroll_student(sid, dept["id"], c_b["id"], s_b["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"

    def test_partial_day_overlap_is_conflict(self):
        """Sections sharing at least one common day with time overlap -> SCHEDULE_CONFLICT."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        # MW 09:00-10:00
        c_a = create_course(sid, dept["id"], credit_hours=3, course_code="PDO-A")
        s_a = create_section(sid, dept["id"], c_a["id"], instructor["id"],
                              schedule_days="MW", schedule_start="09:00", schedule_end="10:00",
                              location="Room-PD")

        # WF 09:30-10:30 (overlaps on W)
        c_b = create_course(sid, dept["id"], credit_hours=3, course_code="PDO-B")
        s_b = create_section(sid, dept["id"], c_b["id"], instructor["id"],
                              schedule_days="WF", schedule_start="09:30", schedule_end="10:30",
                              location="Room-PD")

        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], c_a["id"], s_a["id"], student["id"])

        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], c_b["id"], s_b["id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.SCHEDULE_CONFLICT)


class TestTravelBuffer:
    """Tests for the 10-minute travel buffer between different buildings."""

    def test_travel_buffer_different_locations(self):
        """10-min buffer: section ending 10:00 conflicts with 10:09 start in different building."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        c_a = create_course(sid, dept["id"], credit_hours=3, course_code="TB-A")
        s_a = create_section(sid, dept["id"], c_a["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="09:00", schedule_end="10:00",
                              location="Building-A")

        # Different building, starts at 10:09 (within 10-minute buffer)
        c_b = create_course(sid, dept["id"], credit_hours=3, course_code="TB-B")
        s_b = create_section(sid, dept["id"], c_b["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="10:09", schedule_end="11:09",
                              location="Building-B")

        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], c_a["id"], s_a["id"], student["id"])

        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], c_b["id"], s_b["id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.SCHEDULE_CONFLICT)

    def test_travel_buffer_at_boundary(self):
        """Section ending 10:00 does NOT conflict with 10:10 start in different building."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        c_a = create_course(sid, dept["id"], credit_hours=3, course_code="TBB-A")
        s_a = create_section(sid, dept["id"], c_a["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="09:00", schedule_end="10:00",
                              location="Building-X")

        # Different building, starts at 10:10 (exactly at buffer boundary)
        c_b = create_course(sid, dept["id"], credit_hours=3, course_code="TBB-B")
        s_b = create_section(sid, dept["id"], c_b["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="10:10", schedule_end="11:10",
                              location="Building-Y")

        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], c_a["id"], s_a["id"], student["id"])
        enrollment = enroll_student(sid, dept["id"], c_b["id"], s_b["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"

    def test_no_travel_buffer_same_location(self):
        """No travel buffer when both sections are in the same location."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        c_a = create_course(sid, dept["id"], credit_hours=3, course_code="SL-A")
        s_a = create_section(sid, dept["id"], c_a["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="09:00", schedule_end="10:00",
                              location="Same-Room")

        # Same room, starts at 10:00 -> no buffer needed, no overlap
        c_b = create_course(sid, dept["id"], credit_hours=3, course_code="SL-B")
        s_b = create_section(sid, dept["id"], c_b["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="10:00", schedule_end="11:00",
                              location="Same-Room")

        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], c_a["id"], s_a["id"], student["id"])
        enrollment = enroll_student(sid, dept["id"], c_b["id"], s_b["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"


class TestScheduleConflictRecords:
    """Tests for ScheduleConflict diagnostic records."""

    def test_conflict_creates_record(self):
        """Schedule conflict creates a ScheduleConflict diagnostic record."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        c_a = create_course(sid, dept["id"], credit_hours=3, course_code="REC-A")
        s_a = create_section(sid, dept["id"], c_a["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="09:00", schedule_end="10:00",
                              location="Room-R")

        c_b = create_course(sid, dept["id"], credit_hours=3, course_code="REC-B")
        s_b = create_section(sid, dept["id"], c_b["id"], instructor["id"],
                              schedule_days="MWF", schedule_start="09:00", schedule_end="10:00",
                              location="Room-R")

        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enroll_student(sid, dept["id"], c_a["id"], s_a["id"], student["id"])

        # Try to enroll in conflicting section
        payload = create_enrollment_payload(student["id"])
        api_client.create_enrollment(
            sid, dept["id"], c_b["id"], s_b["id"], payload, TEST_USERS["student_headers"]
        )

        # Check schedule conflicts list
        resp = api_client.list_schedule_conflicts(sid, TEST_USERS["registrar_headers"])
        data, meta = validate_paginated(resp)
        assert len(data) >= 1, "At least one ScheduleConflict record should exist"
        conflict = data[-1]  # Most recent
        assert conflict["student_id"] == student["id"]
        assert conflict["overlap_minutes"] > 0

    def test_schedule_conflicts_registrar_only(self):
        """Only registrar can access schedule conflicts list."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        resp = api_client.list_schedule_conflicts(sid, TEST_USERS["student_headers"])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

        resp = api_client.list_schedule_conflicts(sid, TEST_USERS["professor_headers"])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)
