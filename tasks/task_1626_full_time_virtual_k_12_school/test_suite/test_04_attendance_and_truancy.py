"""Attendance determination and the rolling truancy window."""
from test_helpers import (
    TEST_USERS,
    assert_attendance_record,
    create_attendance_payload,
    create_district,
    create_enrolled_student,
    create_student,
    enroll_student,
    get_student,
    record_attendance,
    set_clock,
    setup_student_with_unexcused_absences,
    validate_success,
    verify_student,
)

ENROLLMENT = TEST_USERS["enrollment_officer_headers"]


def _enrolled_student(district_code="D-120"):
    district = create_district(district_code=district_code, state_code="CA",
                               funding_rate_cents=500, enrollment_cap=50)
    _, student = create_enrolled_student(district=district)
    return student


class TestAttendanceDetermination:
    def test_attendance_status_computed_present(self, api):
        """PRD §3.5: "From these two inputs the server derives the day's
        `attendance_status` at creation time. A day with at least 240
        synchronous minutes — a full four-hour instructional day — and at
        least 2 engagement check-ins is `PRESENT`."

        Design: Corner/entities/computed_field_input_ignored_on_attendance
        """
        student = _enrolled_student("D-105")
        resp = api.create_attendance(
            create_attendance_payload(student["id"],
                                      attendance_date="2026-08-03T00:00:00Z",
                                      synchronous_minutes=300,
                                      engagement_check_ins=5),
            ENROLLMENT,
        )
        record = validate_success(resp, 201)
        assert_attendance_record(record)
        assert record["attendance_status"] == "PRESENT"
        assert record["excused_reason"] is None

    def test_attendance_determination_partial_branch(self, api):
        """PRD §3.5: "Failing that, a day with at least 120 synchronous
        minutes (a half day of live instruction) or at least 2 check-ins is
        `PARTIAL`."

        Design: Corner/calculations/attendance_determination_partial_branch
        """
        student = _enrolled_student("D-120")
        record = record_attendance(student["id"], "2026-08-03T00:00:00Z",
                                   150, 1)
        assert record["attendance_status"] == "PARTIAL", (
            "150 minutes (>= 120 half-day) with 1 check-in (< 2) is PARTIAL")

    def test_attendance_determination_full_day_at_boundary(self, api):
        """PRD §3.5: "All thresholds are inclusive: exactly 240 minutes with
        exactly 2 check-ins earns `PRESENT`, and exactly 120 minutes with no
        check-ins at all still earns `PARTIAL`."

        Design: Corner/calculations/attendance_determination_full_day_at_boundary
        """
        student = _enrolled_student("D-121")
        record = record_attendance(student["id"], "2026-08-03T00:00:00Z",
                                   240, 2)
        assert record["attendance_status"] == "PRESENT", (
            "exactly 240 minutes and exactly 2 check-ins earns PRESENT")

    def test_attendance_determination_absent_below_all_thresholds(self, api):
        """PRD §3.5: "Anything else is `ABSENT_UNEXCUSED`."

        Design: Corner/calculations/attendance_determination_absent_unexcused_below_all_thresholds
        """
        student = _enrolled_student("D-122")
        record = record_attendance(student["id"], "2026-08-03T00:00:00Z",
                                   50, 0)
        assert record["attendance_status"] == "ABSENT_UNEXCUSED", (
            "50 minutes (< 120) and 0 check-ins (< 2) is ABSENT_UNEXCUSED")


class TestTruancyBoundary:
    def test_two_unexcused_days_leave_truancy_flag_false(self, api):
        """PRD §3.5: "`truancy_unexcused_count` is the number of
        `ABSENT_UNEXCUSED` records falling within the window, and the boolean
        `truancy_flag` follows an inclusive threshold: when the count reaches
        3 unexcused days the flag turns true — exactly three unexcused days in
        the window constitutes truancy — and it returns to false whenever the
        count is below that."

        Design: Difficulty/boundary_precision_check/truancy_threshold_exactly_at_boundary
        """
        _, student, _ = setup_student_with_unexcused_absences(2)
        assert student["truancy_unexcused_count"] == 2
        assert student["truancy_flag"] is False, (
            "two unexcused days are below the inclusive threshold of 3")

    def test_third_unexcused_day_sets_truancy_flag_true(self, api):
        """PRD §3.5: "`truancy_unexcused_count` is the number of
        `ABSENT_UNEXCUSED` records falling within the window, and the boolean
        `truancy_flag` follows an inclusive threshold: when the count reaches
        3 unexcused days the flag turns true — exactly three unexcused days in
        the window constitutes truancy — and it returns to false whenever the
        count is below that."
        PRD §3.5: "Recording a new day that comes out `ABSENT_UNEXCUSED`
        immediately recomputes both values, and enrollment resets them, as
        §3.2 notes."

        Design: Difficulty/boundary_precision_check/truancy_threshold_exactly_at_boundary
        """
        _, student, _ = setup_student_with_unexcused_absences(2)
        assert student["truancy_flag"] is False
        record_attendance(student["id"], "2026-08-05T00:00:00Z", 0, 0)
        student = get_student(student["id"])
        assert student["truancy_unexcused_count"] == 3
        assert student["truancy_flag"] is True, (
            "exactly three unexcused days in the window constitutes truancy")


class TestTruancyWindowSemantics:
    def _setup_nine_records_eleven_calendar_days(self):
        """Nine records from 2026-08-03 through 2026-08-13 (an 11-calendar-day
        span): 08-03, 08-05, 08-07 ABSENT_UNEXCUSED; the rest PRESENT."""
        district = create_district(district_code="D-002", state_code="TX",
                                   funding_rate_cents=400, enrollment_cap=100)
        student = create_student(district["id"], legal_name="Bob",
                                 date_of_birth="2011-05-20T00:00:00Z",
                                 grade_level=8)
        student = verify_student(student["id"])
        set_clock("2026-08-03T08:00:00Z")
        student = enroll_student(student)
        record_attendance(student["id"], "2026-08-03T00:00:00Z", 0, 0)
        record_attendance(student["id"], "2026-08-04T00:00:00Z", 300, 3)
        record_attendance(student["id"], "2026-08-05T00:00:00Z", 0, 0)
        record_attendance(student["id"], "2026-08-06T00:00:00Z", 300, 3)
        record_attendance(student["id"], "2026-08-07T00:00:00Z", 0, 0)
        record_attendance(student["id"], "2026-08-10T00:00:00Z", 300, 3)
        record_attendance(student["id"], "2026-08-11T00:00:00Z", 300, 3)
        record_attendance(student["id"], "2026-08-12T00:00:00Z", 300, 3)
        record_attendance(student["id"], "2026-08-13T00:00:00Z", 300, 3)
        set_clock("2026-08-14T08:00:00Z")
        return student["id"]

    def test_truancy_window_measured_by_record_count(self, api):
        """PRD §3.5: "The window covers the ten most recent school days on
        which the student has an attendance record — recency is measured by
        count of records, not by calendar span — and the window's cutoff is
        the date of the tenth most recent record, inclusive. A student with
        fewer than ten records simply has every record inside the window."

        Design: Difficulty/dual_variant_calc/truancy_window_count_record_count_window_vs_calendar_span
        """
        student_id = self._setup_nine_records_eleven_calendar_days()
        student = get_student(student_id)
        assert student["truancy_unexcused_count"] == 3, (
            "all nine records are inside the count-based window, so the three "
            "unexcused days count even though they span 11 calendar days")

    def test_truancy_flag_true_when_window_holds_three_unexcused(self, api):
        """PRD §3.5: "`truancy_unexcused_count` is the number of
        `ABSENT_UNEXCUSED` records falling within the window, and the boolean
        `truancy_flag` follows an inclusive threshold: when the count reaches
        3 unexcused days the flag turns true — exactly three unexcused days in
        the window constitutes truancy — and it returns to false whenever the
        count is below that."

        Design: Difficulty/dual_variant_calc/truancy_window_count_record_count_window_vs_calendar_span
        """
        student_id = self._setup_nine_records_eleven_calendar_days()
        student = get_student(student_id)
        assert student["truancy_flag"] is True


class TestExcusal:
    def test_excuse_absence_decrements_truancy_count(self, api):
        """PRD §3.5: "Excusing an `ABSENT_UNEXCUSED` record drops the window
        count by one and can clear `truancy_flag` when the count falls below
        the threshold; excusing a `PRESENT` or `PARTIAL` record leaves the
        unexcused count unchanged, since those statuses never contributed to
        it."
        PRD §3.5: "An `EnrollmentOfficer` supplies a free-text
        `excused_reason`, and the record moves to `ABSENT_EXCUSED` — a
        transition admitted from `PRESENT`, from `PARTIAL`, and from
        `ABSENT_UNEXCUSED` alike, and rejected with `ERR_INVALID_STATE` from
        any other status."

        Design: Corner/calculations/excuse_absence_decrements_truancy_count
        """
        _, student, absences = setup_student_with_unexcused_absences(3)
        assert student["truancy_unexcused_count"] == 3
        assert student["truancy_flag"] is True
        resp = api.excuse_attendance(absences[0]["id"], "Doctor appointment",
                                     ENROLLMENT)
        record = validate_success(resp, 200)
        assert record["attendance_status"] == "ABSENT_EXCUSED"
        assert record["excused_reason"] == "Doctor appointment"
        student = get_student(student["id"])
        assert student["truancy_unexcused_count"] == 2
        assert student["truancy_flag"] is False, (
            "dropping below the threshold clears the flag")
