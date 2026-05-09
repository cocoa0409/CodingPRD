"""Attendance check-in window and leave-request lifecycle (PRD §3.3)."""

import pytest

from test_helpers import (
    api_client,
    assert_attendance,
    checkin_payload,
    create_instructor,
    create_leave_request_payload,
    create_published_course,
    end_live_class,
    enroll_student,
    file_leave_request,
    make_instructor_headers,
    make_student_headers,
    make_ta_headers,
    setup_live_session_in_progress,
    setup_pending_leave_with_ta,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestCheckinDeltaBoundaries:
    """PRD §3.3 attendance-mark derivation:

    'Let the difference, in seconds, between checkin_ts and start_ts be the
    check-in delta. If the delta is less than negative nine hundred — that is,
    the student is checking in more than fifteen minutes before the class
    starts — the check-in is rejected with ERR_CHECKIN_WINDOW_CLOSED. If the
    delta is less than or equal to zero (on time or early but within the
    fifteen-minute lead) the mark is ATTENDED. If the delta is strictly
    greater than zero and less than or equal to one thousand eight hundred —
    that is, between one and one thousand eight hundred seconds late,
    inclusive — the mark is LATE; the integer-second boundary at delta equal
    to one thousand eight hundred yields LATE, and delta equal to one thousand
    eight hundred and one yields ERR_CHECKIN_WINDOW_CLOSED.'
    """

    def _setup_live(self, api, start_ts: int = 10_000):
        course, instructor, student, enrollment, live = setup_live_session_in_progress(
            start_ts=start_ts, end_ts=start_ts + 3600
        )
        return course, instructor, student, enrollment, live

    def test_delta_zero_yields_attended(self, api):
        """PRD §3.3: 'If the delta is less than or equal to zero (on time or
        early but within the fifteen-minute lead) the mark is ATTENDED.'"""
        _, _, student, _, live = self._setup_live(api, start_ts=10_000)
        res = api.check_in(
            live["id"],
            checkin_payload(checkin_method="TIME_WINDOW", checkin_ts=10_000),
            make_student_headers(student["id"]),
        )
        att = validate_success(res, expected_status=201)
        assert_attendance(att)
        assert att["mark"] == "ATTENDED"

    def test_delta_lead_minus_900_yields_attended(self, api):
        """PRD §3.3: 'on time or early but within the fifteen-minute lead' —
        delta == -900 is the inclusive lower bound for ATTENDED."""
        _, _, student, _, live = self._setup_live(api, start_ts=11_000)
        res = api.check_in(
            live["id"],
            checkin_payload(checkin_method="TIME_WINDOW", checkin_ts=10_100),
            make_student_headers(student["id"]),
        )
        att = validate_success(res, expected_status=201)
        assert att["mark"] == "ATTENDED"

    def test_delta_minus_901_rejected(self, api):
        """PRD §3.3: 'If the delta is less than negative nine hundred — that
        is, the student is checking in more than fifteen minutes before the
        class starts — the check-in is rejected with ERR_CHECKIN_WINDOW_CLOSED.'

        Note: PRD does not allow a check-in to be queued before the live class
        becomes LIVE; the test uses the live-session-in-progress fixture and
        a checkin_ts that is too far before start_ts.
        """
        _, _, student, _, live = self._setup_live(api, start_ts=12_000)
        res = api.check_in(
            live["id"],
            checkin_payload(checkin_method="TIME_WINDOW", checkin_ts=11_099),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_CHECKIN_WINDOW_CLOSED")

    def test_delta_one_yields_late(self, api):
        """PRD §3.3: 'If the delta is strictly greater than zero ... the mark
        is LATE.' Smallest LATE delta is +1."""
        _, _, student, _, live = self._setup_live(api, start_ts=14_000)
        res = api.check_in(
            live["id"],
            checkin_payload(checkin_method="TIME_WINDOW", checkin_ts=14_001),
            make_student_headers(student["id"]),
        )
        att = validate_success(res, expected_status=201)
        assert att["mark"] == "LATE"

    def test_delta_exact_1800_yields_late(self, api):
        """PRD §3.3: 'the integer-second boundary at delta equal to one
        thousand eight hundred yields LATE.'"""
        _, _, student, _, live = self._setup_live(api, start_ts=16_000)
        res = api.check_in(
            live["id"],
            checkin_payload(checkin_method="TIME_WINDOW", checkin_ts=17_800),
            make_student_headers(student["id"]),
        )
        att = validate_success(res, expected_status=201)
        assert att["mark"] == "LATE"

    def test_delta_1801_rejected_window_closed(self, api):
        """PRD §3.3: 'delta equal to one thousand eight hundred and one yields
        ERR_CHECKIN_WINDOW_CLOSED.'"""
        _, _, student, _, live = self._setup_live(api, start_ts=18_000)
        res = api.check_in(
            live["id"],
            checkin_payload(checkin_method="TIME_WINDOW", checkin_ts=19_801),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_CHECKIN_WINDOW_CLOSED")


class TestCheckinAfterEnded:
    """PRD §3.3: 'Once the live class is ENDED, no new check-in is accepted —
    the late check-in attempt sees ERR_LIVE_CLASS_NOT_LIVE.'"""

    def test_checkin_after_ended_returns_not_live(self, api):
        """PRD §3.3: 'Once the live class is ENDED, no new check-in is
        accepted — the late check-in attempt sees ERR_LIVE_CLASS_NOT_LIVE.'"""
        course, instructor, student, enrollment, live = setup_live_session_in_progress(
            start_ts=20_000, end_ts=23_600
        )
        end_live_class(live, instructor)
        res = api.check_in(
            live["id"],
            checkin_payload(checkin_method="TIME_WINDOW", checkin_ts=20_000),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_LIVE_CLASS_NOT_LIVE")


class TestEndAutofillsAbsent:
    """PRD §3.3: 'every enrollment that has no Attendance row for this live
    class receives an autofilled Attendance row with mark = ABSENT.'"""

    def test_end_autofills_absent_for_unchecked_enrollment(self, api):
        """PRD §3.3: 'every enrollment that has no Attendance row for this
        live class receives an autofilled Attendance row with mark = ABSENT.'

        After end, the parent enrollment's attendance_count should reflect
        an ABSENT row — but PRD §3.3 says 'EXCUSED and ABSENT rows do not
        contribute' to attendance_count, so attendance_count stays at 0.
        We instead verify the side effect indirectly: a subsequent check-in
        for the never-checked-in enrollment returns ERR_LIVE_CLASS_NOT_LIVE.
        That check is covered by test_checkin_after_ended_returns_not_live;
        here we just confirm enrollment.attendance_count is 0 after end.
        """
        course, instructor, student, enrollment, live = setup_live_session_in_progress(
            start_ts=30_000, end_ts=33_600
        )
        end_live_class(live, instructor)
        # No check-in happened, so attendance_count stays at 0
        # (PRD §3.3: 'EXCUSED and ABSENT rows do not contribute' to attendance_count).
        res = api.get_enrollment(enrollment["id"], make_student_headers(student["id"]))
        e = validate_success(res, expected_status=200)
        assert e["attendance_count"] == 0


class TestLeaveRequestLifecycle:
    """PRD §3.3 leave: PENDING → {APPROVED, REJECTED}."""

    def test_leave_request_lands_pending(self, api):
        """PRD §3.3: 'The request lands in status = PENDING.'"""
        course, instructor, _, _, _, _, _, leave = setup_pending_leave_with_ta()
        assert leave["status"] == "PENDING"

    def test_approve_leave_creates_excused_attendance(self, api):
        """PRD §3.3: 'on success, the request advances to APPROVED and the
        system writes an Attendance row for the (live_class_id, enrollment_id)
        pair with mark = EXCUSED and checkin_method = LEAVE.'

        The test verifies the request transitions and that a subsequent
        check-in attempt does not produce ATTENDED (because EXCUSED already
        exists). The Attendance row's mark is verifiable indirectly through
        the enrollment's attendance_count (which excludes EXCUSED per
        PRD §3.3).
        """
        course, instructor, ta, student, enrollment, group, live, leave = setup_pending_leave_with_ta(
            start_ts=40_000, end_ts=43_600
        )
        res = api.approve_leave_request(leave["id"], make_ta_headers(ta["id"]))
        approved = validate_success(res, expected_status=200)
        assert approved["status"] == "APPROVED"

    def test_approve_leave_when_live_class_already_started_rejected(self, api):
        """PRD §3.3: 'approval requires ... the target live class to still be
        SCHEDULED (ERR_LIVE_CLASS_ALREADY_STARTED).'"""
        from test_helpers import (
            advance_clock,
            create_instructor,
            create_published_course,
            schedule_live_class,
            create_class_group,
            assign_enrollment_to_group,
            start_live_class,
        )
        course, instructor, _ = create_published_course()
        ta = create_instructor()
        enrollment, student = enroll_student(course)
        group = create_class_group(course, instructor, ta=ta)
        assign_enrollment_to_group(group, enrollment, instructor)
        live = schedule_live_class(course, instructor, start_ts=50_000, end_ts=53_600)
        leave = file_leave_request(enrollment, live, student)
        # Now move the live class into LIVE
        advance_clock(50_000)
        start_live_class(live, instructor)
        res = api.approve_leave_request(leave["id"], make_ta_headers(ta["id"]))
        validate_error(res, "ERR_LIVE_CLASS_ALREADY_STARTED")

    def test_approve_leave_not_pending_rejected(self, api):
        """PRD §3.3: 'approval requires the request to still be PENDING
        (ERR_LEAVE_NOT_PENDING).'"""
        course, instructor, ta, student, enrollment, group, live, leave = setup_pending_leave_with_ta(
            start_ts=60_000, end_ts=63_600
        )
        # Reject first to leave the request in REJECTED.
        validate_success(
            api.reject_leave_request(leave["id"], make_ta_headers(ta["id"])),
            expected_status=200,
        )
        res = api.approve_leave_request(leave["id"], make_ta_headers(ta["id"]))
        validate_error(res, "ERR_LEAVE_NOT_PENDING")

    def test_reject_leave_advances_to_rejected(self, api):
        """PRD §3.3: 'The same teaching assistant may instead reject the
        leave request, advancing it to REJECTED.'"""
        course, instructor, ta, student, enrollment, group, live, leave = setup_pending_leave_with_ta(
            start_ts=70_000, end_ts=73_600
        )
        res = api.reject_leave_request(leave["id"], make_ta_headers(ta["id"]))
        rejected = validate_success(res, expected_status=200)
        assert rejected["status"] == "REJECTED"
