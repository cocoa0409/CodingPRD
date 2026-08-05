"""Hearing calendar: half-open overlap, adjacency, daily capacity, continuance,
slot conservation, and the case-in-litigation hold gate (PRD §3.6, §2.9)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_judge_headers, TEST_USERS,
    assert_court_slot_invariant,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

CLERK = TEST_USERS["clerk_headers"]


# --------------------------------------------------------------------------- #
# Queue A: boundary_precision_check / hearing_adjacent_half_open_intervals      #
# --------------------------------------------------------------------------- #
def test_adjacent_hearing_accepted(api):
    """PRD §3.6: "Because the intervals are half-open, adjacency is allowed — a hearing
    whose start equals another's end does not overlap."

    Design: Difficulty/boundary_precision_check/hearing_adjacent_half_open_intervals_allowed
    """
    ctx = fx.setup_case_with_scheduled_hearing(
        api, court_capacity=2, scheduled_start="2026-06-01T10:00:00Z",
        scheduled_end="2026-06-01T11:00:00Z")
    resp = api.create_hearing(
        f.create_hearing_payload(ctx["case"]["id"], ctx["court"]["id"],
                                 "2026-06-01T11:00:00Z", "2026-06-01T12:00:00Z",
                                 hearing_type="TRIAL"),
        CLERK)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


def test_adjacent_hearing_count_reaches_two(api):
    """PRD §2.9: a court's hearings_scheduled_count "increases by 1 whenever a hearing
    is scheduled". Adjacent [11:00,12:00) does not overlap [10:00,11:00), so both stay
    SCHEDULED and the count is 2.

    Design: Difficulty/boundary_precision_check/hearing_adjacent_half_open_intervals_allowed
    """
    ctx = fx.setup_case_with_scheduled_hearing(
        api, court_capacity=2, scheduled_start="2026-06-01T10:00:00Z",
        scheduled_end="2026-06-01T11:00:00Z")
    get_success_data(api.create_hearing(
        f.create_hearing_payload(ctx["case"]["id"], ctx["court"]["id"],
                                 "2026-06-01T11:00:00Z", "2026-06-01T12:00:00Z",
                                 hearing_type="TRIAL"),
        CLERK))
    court = get_success_data(api.get_court(ctx["court"]["id"], CLERK))
    assert_court_slot_invariant(court, 2)


# --------------------------------------------------------------------------- #
# Queue A: resource_temporal_overlap / hearing_half_open_overlap_rejected       #
# --------------------------------------------------------------------------- #
def test_overlapping_hearing_rejected(api):
    """PRD §3.6: "two intervals conflict when the new start falls before the other's end
    and the other's start falls before the new end. ... An overlap is refused with
    ERR_HEARING_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/hearing_half_open_overlap_rejected_on_court
    """
    ctx = fx.setup_case_with_scheduled_hearing(
        api, court_capacity=2, scheduled_start="2026-06-01T10:00:00Z",
        scheduled_end="2026-06-01T12:00:00Z")
    resp = api.create_hearing(
        f.create_hearing_payload(ctx["case"]["id"], ctx["court"]["id"],
                                 "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z",
                                 hearing_type="TRIAL"),
        CLERK)
    validate_error(resp, ApiErrorId.ERR_HEARING_CONFLICT.value, expected_status=409)


def test_overlapping_hearing_does_not_consume_slot(api):
    """PRD §2.9: a court's hearings_scheduled_count "always equals the number of Hearing
    rows on that court whose status is SCHEDULED". A rejected overlap leaves the count at
    its prior value of 1.

    Design: Difficulty/resource_temporal_overlap/hearing_half_open_overlap_rejected_on_court
    """
    ctx = fx.setup_case_with_scheduled_hearing(
        api, court_capacity=2, scheduled_start="2026-06-01T10:00:00Z",
        scheduled_end="2026-06-01T12:00:00Z")
    api.create_hearing(
        f.create_hearing_payload(ctx["case"]["id"], ctx["court"]["id"],
                                 "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z",
                                 hearing_type="TRIAL"),
        CLERK)
    court = get_success_data(api.get_court(ctx["court"]["id"], CLERK))
    assert_court_slot_invariant(court, 1)


# --------------------------------------------------------------------------- #
# Queue A: compensating_invariant / court_slot_conservation                     #
# --------------------------------------------------------------------------- #
def test_court_slot_conserved_after_schedule_then_cancel(api):
    """PRD §2.9: hearings_scheduled_count "starts at 0 when the court is registered,
    increases by 1 whenever a hearing is scheduled ... and decreases by 1 whenever a
    scheduled hearing leaves SCHEDULED by being held, cancelled, or continued."

    Design: Difficulty/compensating_invariant/court_slot_conservation_on_schedule_then_cancel
    """
    ctx = fx.setup_case_with_scheduled_hearing(
        api, court_capacity=2, scheduled_start="2026-06-01T10:00:00Z",
        scheduled_end="2026-06-01T11:00:00Z")
    hearing = get_success_data(api.transition_hearing(
        ctx["hearing"]["id"], {"to_status": "CANCELLED"}, CLERK))
    court = get_success_data(api.get_court(ctx["court"]["id"], CLERK))
    assert hearing["status"] == "CANCELLED"
    assert_court_slot_invariant(court, 0)


def test_court_slot_increments_on_schedule(api):
    """PRD §2.9: hearings_scheduled_count "increases by 1 whenever a hearing is
    scheduled". Immediately after the single schedule the count reads 1.

    Design: Difficulty/compensating_invariant/court_slot_conservation_on_schedule_then_cancel
    """
    ctx = fx.setup_case_with_scheduled_hearing(
        api, court_capacity=2, scheduled_start="2026-06-01T10:00:00Z",
        scheduled_end="2026-06-01T11:00:00Z")
    court = get_success_data(api.get_court(ctx["court"]["id"], CLERK))
    assert_court_slot_invariant(court, 1)


# --------------------------------------------------------------------------- #
# Queue A: cross_entity_state_dependency / hearing_hold_blocked                 #
# --------------------------------------------------------------------------- #
def test_hold_hearing_case_not_in_litigation_rejected(api):
    """PRD §3.6: "A judge holds a hearing by moving it from SCHEDULED to HELD, which
    requires two things: the parent case must be IN_LITIGATION (otherwise
    ERR_CASE_NOT_IN_LITIGATION), and the current logical-clock instant must be at or
    after scheduled_start."

    Design: Difficulty/cross_entity_state_dependency/hearing_hold_blocked_unless_case_in_litigation
    """
    ctx = fx.setup_case_with_scheduled_hearing(
        api, court_capacity=2, claimed_arrears_cents=600000, answered=True,
        scheduled_start="2026-06-01T10:00:00Z", scheduled_end="2026-06-01T11:00:00Z")
    fx.set_clock(api, "2026-06-01T10:00:00Z")  # clock precondition satisfied
    resp = api.transition_hearing(ctx["hearing"]["id"], {"to_status": "HELD"},
                                  make_judge_headers("judge-1"))
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_LITIGATION.value, expected_status=409)


def test_hold_hearing_blocked_leaves_hearing_scheduled(api):
    """PRD §3.6: holding requires "the parent case must be IN_LITIGATION (otherwise
    ERR_CASE_NOT_IN_LITIGATION)". A rejected hold leaves the hearing SCHEDULED.

    Design: Difficulty/cross_entity_state_dependency/hearing_hold_blocked_unless_case_in_litigation
    """
    ctx = fx.setup_case_with_scheduled_hearing(
        api, court_capacity=2, claimed_arrears_cents=600000, answered=True,
        scheduled_start="2026-06-01T10:00:00Z", scheduled_end="2026-06-01T11:00:00Z")
    fx.set_clock(api, "2026-06-01T10:00:00Z")
    api.transition_hearing(ctx["hearing"]["id"], {"to_status": "HELD"},
                           make_judge_headers("judge-1"))
    hearing = get_success_data(api.get_hearing(ctx["hearing"]["id"], CLERK))
    assert hearing["status"] == "SCHEDULED"


# --------------------------------------------------------------------------- #
# Queue B: continuance + daily capacity                                        #
# --------------------------------------------------------------------------- #
def test_hearing_continuance_creates_successor_and_conserves_slot(api):
    """PRD §3.6: "The original hearing moves from SCHEDULED to CONTINUED and releases its
    slot. In the same operation a successor hearing is created SCHEDULED on the new
    interval ... and the court's hearings_scheduled_count incremented by 1 for the
    successor."

    Design: Corner/state_machines/hearing_continuance_creates_successor_and_conserves_slot
    """
    ctx = fx.setup_case_with_scheduled_hearing(
        api, court_capacity=2, scheduled_start="2026-06-01T10:00:00Z",
        scheduled_end="2026-06-01T11:00:00Z")
    original = get_success_data(api.transition_hearing(
        ctx["hearing"]["id"],
        {"to_status": "CONTINUED", "new_start": "2026-06-05T10:00:00Z",
         "new_end": "2026-06-05T11:00:00Z"},
        CLERK))
    court = get_success_data(api.get_court(ctx["court"]["id"], CLERK))
    assert original["status"] == "CONTINUED"
    assert_court_slot_invariant(court, 1)


def test_hearing_daily_capacity_full_returns_calendar_full(api):
    """PRD §3.6: "the number of SCHEDULED hearings already on that court that fall on the
    same calendar date ... must be below the court's hearing_daily_capacity; if the date
    is already at capacity, the request is refused with ERR_CALENDAR_FULL."

    Design: Corner/validations/hearing_daily_capacity_full_returns_calendar_full
    """
    ctx = fx.setup_case_with_scheduled_hearing(
        api, court_capacity=1, scheduled_start="2026-06-01T10:00:00Z",
        scheduled_end="2026-06-01T11:00:00Z")
    resp = api.create_hearing(
        f.create_hearing_payload(ctx["case"]["id"], ctx["court"]["id"],
                                 "2026-06-01T13:00:00Z", "2026-06-01T14:00:00Z",
                                 hearing_type="TRIAL"),
        CLERK)
    validate_error(resp, ApiErrorId.ERR_CALENDAR_FULL.value, expected_status=409)
