"""Overlap rules whose answer depends on how each interval is measured.

An in-home visit's busy interval is padded by a travel buffer on both ends, so
two visits that never touch on the clock still collide; a virtual visit is padded
by nothing, so two that touch exactly do not collide for the teacher yet fail the
per-case spacing rule. The make-up path re-runs both of those measurements.
"""

from test_helpers import (
    ApiErrorId,
    CM_HEADERS,
    MIDDLE_IN_HOME_RULE,
    MIDDLE_VIRTUAL_RULE,
    accept_assignment,
    activate_case,
    add_support_assignment,
    api_client,
    create_session_payload,
    entries_for_session,
    finalize_safety_review,
    log_session,
    log_student_unavailable_payload,
    makeup_session_payload,
    open_case,
    propose_assignment,
    read_session,
    record_safety_review,
    register_student,
    review_certification,
    schedule_session,
    sessions_for_case,
    set_clock,
    setup_active_case,
    submit_certification,
    validate_error,
    validate_success,
)

CERT_WINDOW = {
    "expected_absence_days": 30,
    "certified_start_date": "2026-09-07",
    "certified_end_date": "2026-10-07",
    "signature_date": "2026-09-01",
}

CLEARED_SAFETY_REVIEW = {
    "hazard_findings": ["UNLIT_ACCESS"],
    "escort_available": False,
}


def _one_teacher_serving_two_in_home_cases() -> dict:
    """Two ACTIVE in-home cases whose PRIMARY assignments both name teacher E-1001,
    with case A already holding a 2026-09-07 09:00-11:00 in-home visit."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    teacher_id = bundle["teacher"]["id"]

    student_b = register_student(student_number="S-0002", full_name="Ben Ortiz")
    case_b = open_case(student_b["id"], delivery_mode="IN_HOME")
    certification_b = submit_certification(
        case_b["id"], physician_npi="1234567891", **CERT_WINDOW
    )
    review_certification(certification_b["id"], "ACCEPT")
    safety_b = record_safety_review(case_b["id"], **CLEARED_SAFETY_REVIEW)
    finalize_safety_review(safety_b["id"])
    assignment_b = propose_assignment(case_b["id"], "PRIMARY", teacher_id)
    bundle["assignment_b"] = accept_assignment(assignment_b["id"], teacher_id)
    bundle["case_b"] = activate_case(case_b["id"])

    bundle["session_a"] = schedule_session(
        bundle["case"]["id"],
        bundle["primary_assignment"]["id"],
        scheduled_start="2026-09-07T09:00:00Z",
        scheduled_end="2026-09-07T11:00:00Z",
        delivery_mode="IN_HOME",
        subject="MATH",
    )
    return bundle


def _book_on_case_b(bundle: dict, start: str, end: str):
    return api_client.create_session(
        create_session_payload(
            bundle["case_b"]["id"],
            bundle["assignment_b"]["id"],
            scheduled_start=start,
            scheduled_end=end,
            delivery_mode="IN_HOME",
            subject="MATH",
        ),
        CM_HEADERS,
    )


def _virtual_case_with_one_ninety_minute_session() -> dict:
    """An ACTIVE virtual case, on a rule with no travel buffer, holding one
    2026-09-14 09:00-10:30 virtual session."""
    bundle = setup_active_case(
        rules=[MIDDLE_VIRTUAL_RULE],
        case={"delivery_mode": "VIRTUAL_SYNC"},
        certification=dict(CERT_WINDOW),
        include_safety_review=False,
    )
    bundle["first_session"] = schedule_session(
        bundle["case"]["id"],
        bundle["primary_assignment"]["id"],
        scheduled_start="2026-09-14T09:00:00Z",
        scheduled_end="2026-09-14T10:30:00Z",
        delivery_mode="VIRTUAL_SYNC",
        subject="MATH",
    )
    return bundle


def _book_virtual(bundle: dict, start: str, end: str, subject: str = "ELA"):
    return api_client.create_session(
        create_session_payload(
            bundle["case"]["id"],
            bundle["primary_assignment"]["id"],
            scheduled_start=start,
            scheduled_end=end,
            delivery_mode="VIRTUAL_SYNC",
            subject=subject,
        ),
        CM_HEADERS,
    )


def _case_with_a_missed_visit_and_a_second_teacher() -> dict:
    """An ACTIVE in-home case with a PRIMARY and a SUPPORT assignment, one missed
    2026-09-07 visit logged STUDENT_UNAVAILABLE, and a 2026-09-08 09:00-11:00 visit
    still scheduled on the primary assignment."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification=dict(CERT_WINDOW),
        safety_review=dict(CLEARED_SAFETY_REVIEW),
    )
    add_support_assignment(bundle, teacher={"max_weekly_caseload_minutes": 600})
    bundle["missed_session"] = schedule_session(
        bundle["case"]["id"],
        bundle["primary_assignment"]["id"],
        scheduled_start="2026-09-07T09:00:00Z",
        scheduled_end="2026-09-07T11:00:00Z",
        delivery_mode="IN_HOME",
        subject="MATH",
    )
    bundle["next_day_session"] = schedule_session(
        bundle["case"]["id"],
        bundle["primary_assignment"]["id"],
        scheduled_start="2026-09-08T09:00:00Z",
        scheduled_end="2026-09-08T11:00:00Z",
        delivery_mode="IN_HOME",
        subject="ELA",
    )
    set_clock("2026-09-07T18:00:00Z")
    bundle["missed_session"] = log_session(
        bundle["missed_session"]["id"],
        bundle["teacher"]["id"],
        log_student_unavailable_payload(
            "MEDICAL", outcome_reason="Hospitalized overnight"
        ),
    )
    return bundle


def _request_makeup(bundle: dict, start: str, end: str):
    return api_client.create_makeup_session(
        bundle["missed_session"]["id"],
        makeup_session_payload(
            bundle["support_assignment"]["id"],
            scheduled_start=start,
            scheduled_end=end,
            delivery_mode="IN_HOME",
            subject="MATH",
        ),
        CM_HEADERS,
    )


def _makeups_of(session_id: str, case_id: str) -> list:
    return [
        session
        for session in sessions_for_case(case_id)
        if session.get("makeup_for_session_id") == session_id
    ]


class TestTravelBufferCreatesAConflictTheClockDoesNotShow:
    """Two visits ninety minutes apart on the clock still collide once padded."""

    def test_buffered_intervals_collide_across_two_different_cases(self):
        """An 11:15 start on a second case is refused because the teacher's 09:00-11:00
        in-home visit is padded out to 11:30 by the travel buffer.

        The PRD states: "A busy interval is the half-open span from `scheduled_start` up
        to but not including `scheduled_end`, extended on both ends by the rule's
        `travel_buffer_minutes` when that particular session's `delivery_mode` is
        `IN_HOME` and extended by nothing at all when it is `VIRTUAL_SYNC`."

        The PRD states: "The serving teacher may not be double-booked: the new session's
        busy interval must not overlap the busy interval of any other session of the
        same teacher whose `status` is `SCHEDULED` or `DELIVERED`."

        Design: Difficulty/resource_temporal_overlap/teacher_busy_interval_extended_by_travel_buffer_collides_across_two_cases
        """
        bundle = _one_teacher_serving_two_in_home_cases()

        validate_error(
            _book_on_case_b(bundle, "2026-09-07T11:15:00Z", "2026-09-07T13:15:00Z"),
            ApiErrorId.ERR_TEACHER_SLOT_CONFLICT.value,
            409,
        )

        assert sessions_for_case(bundle["case_b"]["id"]) == [], (
            "the conflict is only visible by scanning the teacher, not the case"
        )
        assert len(sessions_for_case(bundle["case"]["id"])) == 1

    def test_buffered_intervals_that_touch_exactly_are_accepted(self):
        """A 12:00 start pads back to exactly 11:30, meeting the first interval's padded
        end without overlapping it, and the visit is booked.

        The PRD states: "A busy interval is the half-open span from `scheduled_start` up
        to but not including `scheduled_end`, extended on both ends by the rule's
        `travel_buffer_minutes` when that particular session's `delivery_mode` is
        `IN_HOME` and extended by nothing at all when it is `VIRTUAL_SYNC`."

        Design: Difficulty/resource_temporal_overlap/teacher_busy_interval_extended_by_travel_buffer_collides_across_two_cases
        """
        bundle = _one_teacher_serving_two_in_home_cases()

        booked = validate_success(
            _book_on_case_b(bundle, "2026-09-07T12:00:00Z", "2026-09-07T14:00:00Z"), 201
        )
        assert booked["status"] == "SCHEDULED"
        assert booked["service_date"] == "2026-09-07"
        assert booked["scheduled_minutes"] == 120

        assert read_session(bundle["session_a"]["id"])["status"] == "SCHEDULED", (
            "the earlier visit on the other case is untouched"
        )


class TestVirtualSessionsTouchWithoutATeacherConflict:
    """No travel buffer means the teacher rule is silent where the case rule is not."""

    def test_touching_virtual_intervals_fail_the_case_gap_rather_than_the_teacher_scan(
        self,
    ):
        """A session starting the instant the previous one ends is refused for the
        case's minimum gap, not for a teacher conflict.

        The PRD states: "And two sessions of the same case on the same `service_date`
        must be separated by at least the rule's `min_gap_minutes`, measured as the
        closed-interval gap against every existing session of that case on that date
        whose `status` is `SCHEDULED` or `DELIVERED`: a gap exactly equal to
        `min_gap_minutes` passes, while any smaller gap — including endpoints that
        merely touch — fails with `ERR_SESSION_GAP_TOO_SHORT`."

        Design: Difficulty/resource_temporal_overlap/virtual_sessions_touch_without_teacher_conflict_yet_violate_the_case_gap_rule
        """
        bundle = _virtual_case_with_one_ninety_minute_session()

        error = validate_error(
            _book_virtual(bundle, "2026-09-14T10:30:00Z", "2026-09-14T12:00:00Z"),
            ApiErrorId.ERR_SESSION_GAP_TOO_SHORT.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_TEACHER_SLOT_CONFLICT.value, (
            "with no travel buffer the touching intervals do not overlap"
        )
        assert len(sessions_for_case(bundle["case"]["id"])) == 1

    def test_a_ten_minute_gap_passes_and_fills_the_day_exactly(self):
        """A 10:40 start leaves a gap of exactly the minimum, is booked, and brings the
        day to exactly 180 minutes, after which a further thirty minutes is refused.

        The PRD states: "Finally, the student's day is capped: the sum of
        `scheduled_minutes` over the case's sessions with `status` `SCHEDULED` or
        `DELIVERED` on the same `service_date`, plus the new session's own
        `scheduled_minutes`, may not exceed the rule's `max_daily_minutes`; a total
        exactly equal to `max_daily_minutes` passes, and any excess is
        `ERR_STUDENT_DAILY_LIMIT`."

        Design: Difficulty/resource_temporal_overlap/virtual_sessions_touch_without_teacher_conflict_yet_violate_the_case_gap_rule
        """
        bundle = _virtual_case_with_one_ninety_minute_session()

        booked = validate_success(
            _book_virtual(bundle, "2026-09-14T10:40:00Z", "2026-09-14T12:10:00Z"), 201
        )
        assert booked["status"] == "SCHEDULED"
        assert booked["scheduled_minutes"] == 90

        same_day = [
            session
            for session in sessions_for_case(bundle["case"]["id"])
            if session["service_date"] == "2026-09-14"
        ]
        assert sum(session["scheduled_minutes"] for session in same_day) == 180

        validate_error(
            _book_virtual(
                bundle, "2026-09-14T12:20:00Z", "2026-09-14T12:50:00Z", "SCIENCE"
            ),
            ApiErrorId.ERR_STUDENT_DAILY_LIMIT.value,
            422,
        )
        assert len(sessions_for_case(bundle["case"]["id"])) == 2, (
            "the day is full even though the ten-minute gap would have been legal"
        )


class TestMakeupPathReRunsEverySchedulingGuard:
    """A second creation path inherits the spacing rule and adds a uniqueness rule."""

    def test_the_makeup_is_refused_for_a_ten_minute_gap_on_the_other_teacher(self):
        """Placing the make-up ten minutes after the case's existing visit is refused,
        even though it names a different teacher's assignment.

        The PRD states: "Every scheduling check listed above — duration, teacher slot
        conflict, case minimum gap, daily limit, certified window, safety review
        presence and expiry, blocked clearance, in-home permission, teacher clearance,
        escort confirmation, active assignment, and in-service case — applies to a
        make-up session identically."

        The PRD states: "A `STUDENT_UNAVAILABLE` outcome requires the payload to carry
        an `absence_kind` of either `MEDICAL` or `UNEXCUSED`, advances the session
        `SCHEDULED → STUDENT_UNAVAILABLE`, sets `credited_minutes` to 0, and appends a
        ledger row with `attendance_code` `HB_ABSENT_MEDICAL` when `absence_kind` is
        `MEDICAL` and `HB_ABSENT_UNEXCUSED` when it is `UNEXCUSED`, with
        `apportionment_minutes` 0."

        Design: Difficulty/resource_temporal_overlap/makeup_session_inherits_same_day_spacing_boundary_on_a_different_assignment
        """
        bundle = _case_with_a_missed_visit_and_a_second_teacher()
        missed = bundle["missed_session"]
        assert missed["status"] == "STUDENT_UNAVAILABLE"
        assert missed["credited_minutes"] == 0

        entries = entries_for_session(missed["id"])
        assert [entry["attendance_code"] for entry in entries] == ["HB_ABSENT_MEDICAL"]
        assert entries[0]["apportionment_minutes"] == 0

        validate_error(
            _request_makeup(bundle, "2026-09-08T11:10:00Z", "2026-09-08T12:10:00Z"),
            ApiErrorId.ERR_SESSION_GAP_TOO_SHORT.value,
            409,
        )
        assert _makeups_of(missed["id"], bundle["case"]["id"]) == [], (
            "the refused make-up leaves no session pointing at the missed visit"
        )

    def test_a_fifteen_minute_gap_books_the_makeup_and_consumes_the_missed_visit(self):
        """Shifting the make-up to exactly the minimum gap books it, and a second
        make-up for the same missed visit is then refused.

        The PRD states: "The session being made up must have `status`
        `STUDENT_UNAVAILABLE`, `TEACHER_CANCELLED` or `SAFETY_ABORTED`, and it must not
        already be referenced by another session's `makeup_for_session_id`; either
        failure is `ERR_MAKEUP_NOT_ELIGIBLE`."

        Design: Difficulty/resource_temporal_overlap/makeup_session_inherits_same_day_spacing_boundary_on_a_different_assignment
        """
        bundle = _case_with_a_missed_visit_and_a_second_teacher()
        missed = bundle["missed_session"]

        makeup = validate_success(
            _request_makeup(bundle, "2026-09-08T11:15:00Z", "2026-09-08T12:15:00Z"), 201
        )
        assert makeup["status"] == "SCHEDULED"
        assert makeup["makeup_for_session_id"] == missed["id"]
        assert makeup["scheduled_minutes"] == 60
        assert makeup["service_date"] == "2026-09-08"

        same_day = [
            session
            for session in sessions_for_case(bundle["case"]["id"])
            if session["service_date"] == "2026-09-08"
        ]
        assert sum(session["scheduled_minutes"] for session in same_day) == 180

        validate_error(
            _request_makeup(bundle, "2026-09-09T09:00:00Z", "2026-09-09T10:00:00Z"),
            ApiErrorId.ERR_MAKEUP_NOT_ELIGIBLE.value,
            422,
        )
        assert len(_makeups_of(missed["id"], bundle["case"]["id"])) == 1, (
            "one missed visit can be made up exactly once"
        )
