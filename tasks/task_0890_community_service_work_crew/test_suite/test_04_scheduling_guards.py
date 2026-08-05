"""Work-session scheduling guards: participant rest buffer, site capacity, supervisor
double-booking, and the buffer-vs-capacity validation precedence.

Covers Difficulty queue: resource_temporal_overlap (participant buffer + site capacity)
and priority_pair_validation_conflict (overlap beats capacity). Covers Corner queue:
supervisor double-booking.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_work_session_payload,
    TEST_USERS,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]


# ============================ Difficulty: participant rest buffer
def test_participant_rest_buffer_gap_below_60_rejected(api):
    """PRD §3.4: "Compute the gap in minutes between the candidate and each such session, treating any overlap
    as a gap of zero. If the smallest such gap is under 60 minutes the schedule is refused
    with `ERR_SESSION_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rto_participant_rest_buffer_violation
    """
    s = fx.active_placement_scenario(capacity_slots=5, court_case_number="CR-15")
    fx.new_session(s["placement_id"], "2026-06-05T09:00:00Z", "2026-06-05T11:00:00Z")
    # candidate starts 30 minutes after the first ends -> gap 30 < 60
    res = api.create_work_session(create_work_session_payload(
        s["placement_id"], "2026-06-05T11:30:00Z", "2026-06-05T12:30:00Z"), COORD)
    validate_error(res, "ERR_SESSION_OVERLAP", 409)


def test_participant_rest_buffer_gap_exactly_60_allowed(api):
    """PRD §3.4: "A gap of exactly 60 minutes is allowed; 59 is rejected. The participant must therefore have
    at least a one-hour rest between the end of one session and the start of the next."

    Design: Difficulty/resource_temporal_overlap/rto_participant_rest_buffer_violation
    """
    s = fx.active_placement_scenario(capacity_slots=5, court_case_number="CR-15B")
    fx.new_session(s["placement_id"], "2026-06-05T09:00:00Z", "2026-06-05T11:00:00Z")
    # candidate starts exactly 60 minutes after the first ends -> allowed
    res = api.create_work_session(create_work_session_payload(
        s["placement_id"], "2026-06-05T12:00:00Z", "2026-06-05T13:00:00Z"), COORD)
    data = validate_success(res, 201)
    assert data["attendance_status"] == "SCHEDULED"


# ============================ Difficulty: site aggregate capacity
def test_site_capacity_exceeded_across_participants(api):
    """PRD §3.4: "Count the other sessions on the same site whose `attendance_status` is `SCHEDULED` or
    `CHECKED_IN` and whose half-open interval shares any instant with the candidate. If
    adding this session would make the concurrent count exceed the site's `capacity_slots`,
    the schedule is refused with `ERR_SITE_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rto_site_capacity_aggregate_overlap
    """
    t = fx.two_placements_same_site(capacity_slots=1, same_supervisor=False)
    fx.new_session(t["placement1_id"], "2026-06-05T09:00:00Z", "2026-06-05T11:00:00Z")
    res = api.create_work_session(create_work_session_payload(
        t["placement2_id"], "2026-06-05T10:00:00Z", "2026-06-05T12:00:00Z"), COORD)
    validate_error(res, "ERR_SITE_CAPACITY_EXCEEDED", 409)


def test_site_capacity_touching_intervals_not_concurrent(api):
    """PRD §3.4: "Capacity is a half-open interval count, so a session that starts exactly when another ends
    does not count as concurrent."

    Design: Difficulty/resource_temporal_overlap/rto_site_capacity_aggregate_overlap
    """
    t = fx.two_placements_same_site(capacity_slots=1)
    fx.new_session(t["placement1_id"], "2026-06-05T09:00:00Z", "2026-06-05T11:00:00Z")
    # second session starts exactly when the first ends -> not concurrent, allowed
    res = api.create_work_session(create_work_session_payload(
        t["placement2_id"], "2026-06-05T11:00:00Z", "2026-06-05T13:00:00Z"), COORD)
    data = validate_success(res, 201)
    assert data["attendance_status"] == "SCHEDULED"


# ============================ Difficulty: overlap (buffer) beats capacity
def test_overlap_beats_capacity_returns_session_overlap(api):
    """PRD §2.9: "and then the specific state and business guards (referral-not-active, placement-not-active,
    waiver, site-accepting, insurance, self-approval, session buffers, capacity, hours
    limits) described in §3."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_schedule_overlap_and_capacity_temporal_wins
    """
    s = fx.active_placement_scenario(capacity_slots=1, court_case_number="CR-10")
    fx.new_session(s["placement_id"], "2026-06-05T09:00:00Z", "2026-06-05T11:00:00Z")
    # same participant, overlapping window on a capacity-1 site: both buffer and capacity
    # would fail; the session-buffer guard is ordered ahead of capacity.
    res = api.create_work_session(create_work_session_payload(
        s["placement_id"], "2026-06-05T09:30:00Z", "2026-06-05T10:30:00Z"), COORD)
    validate_error(res, "ERR_SESSION_OVERLAP", 409)


def test_overlap_beats_capacity_no_session_created(api):
    """PRD §3.4: "If the smallest such gap is under 60 minutes the schedule is refused with
    `ERR_SESSION_OVERLAP` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_schedule_overlap_and_capacity_temporal_wins
    """
    s = fx.active_placement_scenario(capacity_slots=1, court_case_number="CR-10B")
    fx.new_session(s["placement_id"], "2026-06-05T09:00:00Z", "2026-06-05T11:00:00Z")
    api.create_work_session(create_work_session_payload(
        s["placement_id"], "2026-06-05T09:30:00Z", "2026-06-05T10:30:00Z"), COORD)
    data, meta = validate_paginated(
        api.list_work_sessions(COORD, params={"placement_id": s["placement_id"]}))
    assert meta["total_count"] == 1


# ============================ Corner: supervisor double-booking
def test_supervisor_double_booked_rejected(api):
    """PRD §3.4: "The placement's assigned supervisor must not already staff a session whose interval overlaps
    the candidate's. Intervals are treated as half-open, so two sessions that merely touch
    end-to-start are considered adjacent and allowed; genuine overlap is refused with
    `ERR_SUPERVISOR_DOUBLE_BOOKED` (HTTP 409)."

    Design: Corner/validations/supervisor_double_booked_rejected
    """
    t = fx.two_placements_same_site(capacity_slots=5)
    fx.new_session(t["placement1_id"], "2026-06-05T09:00:00Z", "2026-06-05T11:00:00Z")
    res = api.create_work_session(create_work_session_payload(
        t["placement2_id"], "2026-06-05T10:00:00Z", "2026-06-05T12:00:00Z"), COORD)
    validate_error(res, "ERR_SUPERVISOR_DOUBLE_BOOKED", 409)
