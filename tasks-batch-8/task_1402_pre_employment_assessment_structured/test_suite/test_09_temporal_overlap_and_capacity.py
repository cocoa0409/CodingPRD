"""Resource temporal overlap: half-open interviewer calendar, aggregate daily
capacity, and the closed administration window on assessments."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_active_cycle,
    create_calibrated_interviewer,
    create_candidate,
    invite_candidate,
    schedule_assessment,
    invite_and_complete_candidate,
    create_session_payload,
    set_clock_payload,
    complete_assessment_payload,
)

ADMIN = TEST_USERS["admin_headers"]
HM = TEST_USERS["hm_headers"]


def _base_setup(capacity=8):
    """Cycle ACTIVE; c1 COMPLETED raw 72; iv1 CALIBRATED for the pinned guide."""
    ctx = setup_active_cycle(max_sessions_per_day=capacity)
    guide = ctx["guide"]
    cycle = ctx["cycle"]
    interviewer, _cal = create_calibrated_interviewer(guide["id"])
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    return ctx, interviewer, c1


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/interviewer_calendar_half_open_adjacency
# ---------------------------------------------------------------------------

def test_interviewer_calendar_adjacency_allowed(api):
    """PRD §3.6: "the interviewer must not be double-booked, judged on half-open
    intervals so that a conflict exists exactly when the new session starts before an
    existing `SCHEDULED`, `COMPLETED`, or `SCORED` session of the same interviewer ends
    and ends after that existing session starts — a new session starting at the precise
    instant an existing one ends is adjacent and allowed".

    Design: Difficulty/resource_temporal_overlap/interviewer_calendar_half_open_adjacency
    """
    ctx, interviewer, c1 = _base_setup()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    # s1 [10:00, 11:00)
    resp = api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-12T10:00:00Z", scheduled_end="2026-08-12T11:00:00Z"), HM)
    validate_success(resp, expected_status=201)
    # s2 [11:00, 12:00) — adjacent at 11:00
    resp = api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-12T11:00:00Z", scheduled_end="2026-08-12T12:00:00Z"), HM)
    validate_success(resp, expected_status=201)
    # s4 [09:00, 10:00) — adjacent on the other side
    resp = api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-12T09:00:00Z", scheduled_end="2026-08-12T10:00:00Z"), HM)
    validate_success(resp, expected_status=201)


def test_interviewer_calendar_overlap_rejected(api):
    """PRD §3.6: "the interviewer must not be double-booked, judged on half-open
    intervals so that a conflict exists exactly when the new session starts before an
    existing `SCHEDULED`, `COMPLETED`, or `SCORED` session of the same interviewer ends
    and ends after that existing session starts — a new session starting at the precise
    instant an existing one ends is adjacent and allowed — else
    `ERR_INTERVIEWER_DOUBLE_BOOKED` (HTTP 409)".

    [10:30, 11:30) overlaps [10:00, 11:00): 10:30 < 11:00 and 11:30 > 10:00.

    Design: Difficulty/resource_temporal_overlap/interviewer_calendar_half_open_adjacency
    """
    ctx, interviewer, c1 = _base_setup()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    validate_success(api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-12T10:00:00Z", scheduled_end="2026-08-12T11:00:00Z"), HM),
        expected_status=201)
    resp = api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-12T10:30:00Z", scheduled_end="2026-08-12T11:30:00Z"), HM)
    validate_error(resp, ApiErrorId.ERR_INTERVIEWER_DOUBLE_BOOKED)


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/cycle_daily_capacity_aggregate_semantics
# ---------------------------------------------------------------------------

def test_cycle_daily_capacity_rejects_max_plus_one_without_overlap(api):
    """PRD §3.6: "the cycle's daily capacity, an aggregate rather than a pairwise rule,
    under which the count of the cycle's sessions falling on the UTC calendar day of the
    new `scheduled_start` with status `SCHEDULED`, `COMPLETED`, or `SCORED` must remain
    below `max_sessions_per_day`, the booking that would push the count past the cap
    being rejected with `ERR_CYCLE_DAILY_CAPACITY_EXCEEDED` (HTTP 409) even when it
    overlaps nothing".

    max_sessions_per_day == 2; three disjoint sessions with three distinct
    interviewers on 2026-08-12 -> the third is rejected.

    Design: Difficulty/resource_temporal_overlap/cycle_daily_capacity_aggregate_semantics
    """
    ctx = setup_active_cycle(max_sessions_per_day=2, openings_count=3)
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    iv1, _ = create_calibrated_interviewer(guide["id"], full_name="Ivy One", email="ivy1@x.com")
    iv2, _ = create_calibrated_interviewer(guide["id"], full_name="Ivy Two", email="ivy2@x.com")
    iv3, _ = create_calibrated_interviewer(guide["id"], full_name="Ivy Three", email="ivy3@x.com")
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    c2 = create_candidate(external_ref="C-2", full_name="Cand Two", email="c2@x.com",
                          group_code="GROUP_B")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=60)
    invite_and_complete_candidate(cycle["id"], c2["id"], raw_score=60)

    validate_success(api.create_session(cycle["id"], create_session_payload(
        c1["id"], iv1["id"], guide["id"],
        scheduled_start="2026-08-12T09:00:00Z", scheduled_end="2026-08-12T10:00:00Z"), HM),
        expected_status=201)
    validate_success(api.create_session(cycle["id"], create_session_payload(
        c2["id"], iv2["id"], guide["id"],
        scheduled_start="2026-08-12T10:00:00Z", scheduled_end="2026-08-12T11:00:00Z"), HM),
        expected_status=201)
    # Third disjoint session on the same UTC day would push the count to 3 > 2
    resp = api.create_session(cycle["id"], create_session_payload(
        c1["id"], iv3["id"], guide["id"],
        scheduled_start="2026-08-12T11:00:00Z", scheduled_end="2026-08-12T12:00:00Z"), HM)
    validate_error(resp, ApiErrorId.ERR_CYCLE_DAILY_CAPACITY_EXCEEDED)


def test_cycle_daily_capacity_reaches_max_exactly(api):
    """PRD §3.6: "the cycle's daily capacity, an aggregate rather than a pairwise rule,
    under which the count of the cycle's sessions falling on the UTC calendar day of
    the new `scheduled_start` with status `SCHEDULED`, `COMPLETED`, or `SCORED` must
    remain below `max_sessions_per_day`".

    With max_sessions_per_day == 2 the second same-day session reaches the cap exactly
    and is admitted.

    Design: Difficulty/resource_temporal_overlap/cycle_daily_capacity_aggregate_semantics
    """
    ctx = setup_active_cycle(max_sessions_per_day=2, openings_count=3)
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    iv1, _ = create_calibrated_interviewer(guide["id"], full_name="Ivy One", email="ivy1@x.com")
    iv2, _ = create_calibrated_interviewer(guide["id"], full_name="Ivy Two", email="ivy2@x.com")
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    c2 = create_candidate(external_ref="C-2", full_name="Cand Two", email="c2@x.com",
                          group_code="GROUP_B")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=60)
    invite_and_complete_candidate(cycle["id"], c2["id"], raw_score=60)

    s1 = validate_success(api.create_session(cycle["id"], create_session_payload(
        c1["id"], iv1["id"], guide["id"],
        scheduled_start="2026-08-12T09:00:00Z", scheduled_end="2026-08-12T10:00:00Z"), HM),
        expected_status=201)
    s2 = validate_success(api.create_session(cycle["id"], create_session_payload(
        c2["id"], iv2["id"], guide["id"],
        scheduled_start="2026-08-12T10:00:00Z", scheduled_end="2026-08-12T11:00:00Z"), HM),
        expected_status=201)
    assert s1["status"] == "SCHEDULED"
    assert s2["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/administration_window_closed_interval_completion
# ---------------------------------------------------------------------------

def test_assessment_completes_at_exact_window_end(api):
    """PRD §3.5: "The interval is closed at both ends, so starting or completing at
    exactly the effective end instant is valid".

    Design: Difficulty/resource_temporal_overlap/administration_window_closed_interval_completion
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    a1 = invite_candidate(cycle["id"], c1["id"])
    schedule_assessment(a1["id"], scheduled_for="2026-08-19T09:00:00Z")
    # Clock at exactly administration_window_end 2026-08-20T00:00:00Z
    api.set_clock(set_clock_payload("2026-08-20T00:00:00Z"), ADMIN)
    get_success_data(api.start_assessment(a1["id"], HM))
    resp = api.complete_assessment(a1["id"], complete_assessment_payload(raw_score=66), HM)
    data = validate_success(resp)
    assert data["admin_status"] == "COMPLETED"


def test_assessment_start_one_second_past_window_end_rejected(api):
    """PRD §3.5: "outside it, the failure is `ERR_OUTSIDE_ADMINISTRATION_WINDOW`".

    One second past administration_window_end is outside the closed interval.

    Design: Difficulty/resource_temporal_overlap/administration_window_closed_interval_completion
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    c2 = create_candidate(external_ref="C-2", full_name="Cand Two", email="c2@x.com",
                          group_code="GROUP_B")
    a2 = invite_candidate(cycle["id"], c2["id"])
    schedule_assessment(a2["id"], scheduled_for="2026-08-19T09:00:00Z")
    api.set_clock(set_clock_payload("2026-08-20T00:00:01Z"), ADMIN)
    resp = api.start_assessment(a2["id"], HM)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_ADMINISTRATION_WINDOW)
