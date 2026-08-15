"""Coach calendar conflicts: half-open session overlap and the strict
15-minute workshop buffer (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    schedule_session,
    schedule_session_ok,
    setup_buffer_families,
    setup_overlap_families,
    validate_error,
)


def test_back_to_back_sessions_allowed(api):
    """PRD §3.6: "Rule A is a half-open overlap against the coach's other
    `SCHEDULED` sessions: a conflict exists when the new session starts before
    an existing session ends and ends after that session starts — rejected with
    `ERR_COACH_DOUBLE_BOOKED` — while strictly back-to-back adjacency, where
    one session's end equals the other's start, is allowed."

    Design: Difficulty/resource_temporal_overlap/coach_session_half_open_adjacency
    """
    ctx = setup_overlap_families()
    coach = ctx["coach"]
    leg_a, leg_b = ctx["A"], ctx["B"]
    schedule_session_ok(
        leg_a["plan"]["id"], coach["id"], leg_a["package"]["id"],
        "2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z",
    )
    # [16:00, 17:00) against [15:00, 16:00): end == start adjacency is allowed.
    adjacent = schedule_session_ok(
        leg_b["plan"]["id"], coach["id"], leg_b["package"]["id"],
        "2026-08-10T16:00:00Z", "2026-08-10T17:00:00Z",
    )
    assert adjacent["attendance_state"] == "SCHEDULED"


def test_overlapping_sessions_rejected(api):
    """PRD §3.6: "a conflict exists when the new session starts before an
    existing session ends and ends after that session starts — rejected with
    `ERR_COACH_DOUBLE_BOOKED`"

    Design: Difficulty/resource_temporal_overlap/coach_session_half_open_adjacency
    """
    ctx = setup_overlap_families()
    coach = ctx["coach"]
    leg_a, leg_c = ctx["A"], ctx["C"]
    schedule_session_ok(
        leg_a["plan"]["id"], coach["id"], leg_a["package"]["id"],
        "2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z",
    )
    # [15:30, 16:30): 15:30 < 16:00 and 16:30 > 15:00 overlaps session A.
    resp = schedule_session(
        leg_c["plan"]["id"], coach["id"], leg_c["package"]["id"],
        "2026-08-10T15:30:00Z", "2026-08-10T16:30:00Z",
    )
    validate_error(resp, ApiErrorId.ERR_COACH_DOUBLE_BOOKED)


def test_session_exactly_fifteen_minutes_clear_of_workshop_allowed(api):
    """PRD §3.6: "Rule B is a buffered overlap against every `OPEN` or `LOCKED`
    workshop the same coach facilitates: a conflict exists when the new session
    starts less than 15 minutes after the workshop's end or ends less than 15
    minutes before the workshop's start — rejected with
    `ERR_COACH_BUFFER_CONFLICT` — while leaving exactly 15 minutes clear is
    allowed because the comparison is strict."

    Design: Difficulty/resource_temporal_overlap/workshop_buffer_fifteen_minute_semantics
    """
    ctx = setup_buffer_families()
    coach = ctx["coach"]
    leg_a = ctx["A"]
    # Workshop runs 10:00-11:45; starting at 12:00 leaves exactly 15 minutes.
    session = schedule_session_ok(
        leg_a["plan"]["id"], coach["id"], leg_a["package"]["id"],
        "2026-08-10T12:00:00Z", "2026-08-10T13:00:00Z",
    )
    assert session["attendance_state"] == "SCHEDULED"


def test_session_inside_workshop_buffer_rejected(api):
    """PRD §3.6: "a conflict exists when the new session starts less than 15
    minutes after the workshop's end or ends less than 15 minutes before the
    workshop's start — rejected with `ERR_COACH_BUFFER_CONFLICT`"

    Design: Difficulty/resource_temporal_overlap/workshop_buffer_fifteen_minute_semantics
    """
    ctx = setup_buffer_families()
    coach = ctx["coach"]
    leg_b = ctx["B"]
    # [11:00, 11:59) starts before 11:45+15min and ends after 10:00-15min:
    # inside the buffered window.
    resp = schedule_session(
        leg_b["plan"]["id"], coach["id"], leg_b["package"]["id"],
        "2026-08-10T11:00:00Z", "2026-08-10T11:59:00Z",
    )
    validate_error(resp, ApiErrorId.ERR_COACH_BUFFER_CONFLICT)
