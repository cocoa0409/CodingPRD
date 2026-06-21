"""Pairing lifecycle: state-machine guards (BID_OPEN re-open, COMPLETED lockdown),
FlightLeg closed-interval overlap, and immediate-consistency of the award response.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    setup_clean_world,
    setup_pairing_in_bid_open,
    setup_completed_pairing_for_crew,
    setup_scheduled_captain_assignment,
    create_pairing,
    add_revenue_leg,
    open_bidding,
    submit_bid,
    create_crew_member,
    create_flight_leg_payload,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# Invalid-transition: open-bidding on a Pairing already in BID_OPEN
# ---------------------------------------------------------------------

def test_open_bidding_on_already_bid_open_returns_invalid_state(api, planner_headers):
    """PRD §2.9: "State eligibility: the target resource must currently be in
    a state from which the requested transition is defined (else `ERR_INVALID_STATE`)."
    PRD §3.1: "A planner opens bidding on a `DRAFT` Pairing, transitioning
    `state` to `BID_OPEN`".

    Design: Corner/state_machines/open_bidding_on_already_bid_open_returns_invalid_state
    """
    pairing = setup_pairing_in_bid_open()
    res = api.open_pairing_bidding(pairing["id"], planner_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ---------------------------------------------------------------------
# Terminal-state lockdown: cancel from COMPLETED
# ---------------------------------------------------------------------

def test_cancel_pairing_from_completed_terminal_lockdown(api, planner_headers):
    """PRD §3.1: "No cancellation path exists out of `BID_CLOSED`, `AWARDED`,
    `IN_PROGRESS`, or any terminal state; an attempt is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_pairing_from_completed_terminal_lockdown
    """
    _cm, pairing, _a = setup_completed_pairing_for_crew()
    assert pairing["state"] == "COMPLETED"
    res = api.cancel_pairing(pairing["id"], planner_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ---------------------------------------------------------------------
# FlightLeg overlap within a Pairing — closed-interval semantics
# ---------------------------------------------------------------------

def test_flight_leg_overlap_within_pairing_touching_boundary_rejected(api, planner_headers):
    """PRD §2.12: "FlightLeg overlap within a Pairing uses **closed** intervals
    on `[scheduled_departure_utc, scheduled_arrival_utc]`: two legs that touch
    at a single instant are in conflict."
    PRD §3.1: "Two distinct legs of the same Pairing must not have overlapping
    `[scheduled_departure_utc, scheduled_arrival_utc]` windows under
    closed-interval semantics — even legs that merely touch at a single instant
    are in conflict — and an overlap is rejected with `ERR_LEG_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/flight_leg_overlap_within_pairing_closed_interval
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    pairing = create_pairing(
        pairing_code="P-2026-140",
        scheduled_start_utc="2026-06-02T00:00:00Z",
        scheduled_end_utc="2026-06-02T10:00:00Z",
        bidding_close_utc="2026-06-01T12:00:00Z",
    )
    # First leg [01:00, 07:00]
    add_revenue_leg(
        pairing["id"],
        leg_sequence=1,
        departure="LAX",
        arrival="JFK",
        scheduled_departure_utc="2026-06-02T01:00:00Z",
        scheduled_arrival_utc="2026-06-02T07:00:00Z",
    )
    # Second leg touches at 07:00 — must be rejected under closed-interval semantics.
    res = api.create_flight_leg(
        pairing["id"],
        create_flight_leg_payload(
            leg_sequence=2,
            departure_airport="JFK",
            arrival_airport="MIA",
            scheduled_departure_utc="2026-06-02T07:00:00Z",
            scheduled_arrival_utc="2026-06-02T08:00:00Z",
            leg_type="REVENUE",
        ),
        planner_headers,
    )
    validate_error(res, "ERR_LEG_OVERLAP", expected_status=422)


def test_flight_leg_overlap_within_pairing_strict_overlap_rejected(api, planner_headers):
    """PRD §3.1: "Two distinct legs of the same Pairing must not have overlapping
    `[scheduled_departure_utc, scheduled_arrival_utc]` windows under
    closed-interval semantics — even legs that merely touch at a single instant
    are in conflict — and an overlap is rejected with `ERR_LEG_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/flight_leg_overlap_within_pairing_closed_interval
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    pairing = create_pairing(
        pairing_code="P-2026-141",
        scheduled_start_utc="2026-06-02T00:00:00Z",
        scheduled_end_utc="2026-06-02T10:00:00Z",
        bidding_close_utc="2026-06-01T12:00:00Z",
    )
    # First leg [01:00, 07:00]
    add_revenue_leg(
        pairing["id"],
        leg_sequence=1,
        departure="LAX",
        arrival="JFK",
        scheduled_departure_utc="2026-06-02T01:00:00Z",
        scheduled_arrival_utc="2026-06-02T07:00:00Z",
    )
    # Second leg strictly overlapping [06:00, 08:00] — must be rejected.
    res = api.create_flight_leg(
        pairing["id"],
        create_flight_leg_payload(
            leg_sequence=2,
            departure_airport="JFK",
            arrival_airport="MIA",
            scheduled_departure_utc="2026-06-02T06:00:00Z",
            scheduled_arrival_utc="2026-06-02T08:00:00Z",
            leg_type="REVENUE",
        ),
        planner_headers,
    )
    validate_error(res, "ERR_LEG_OVERLAP", expected_status=422)


# ---------------------------------------------------------------------
# Immediate consistency on /award
# ---------------------------------------------------------------------

def test_award_response_carries_awarded_state_immediately(api, planner_headers):
    """PRD §3.1: "Finally `state` flips to `AWARDED` and `version` increments."
    PRD §2.4: "`version` (integer): a monotonically increasing counter that
    starts at 1 on creation and increments by exactly one on every mutation."

    Design: Corner/consistency_model/immediate_consistency_award_visible_in_response
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    cm = create_crew_member(employee_code="AB0900", seniority_number=900)
    pairing = create_pairing(pairing_code="P-2026-900")
    add_revenue_leg(pairing["id"])
    open_bidding(pairing["id"])
    submit_bid(pairing["id"], cm, requested_seat="CAPTAIN")
    set_clock("2026-06-01T12:00:01Z")
    # Re-read to get the version after auto-close cascade.
    p_after_close = api.get_pairing(pairing["id"], planner_headers)
    p_after_close_data = validate_success(p_after_close, 200)
    expected_version = p_after_close_data["version"]

    res = api.award_pairing(
        pairing["id"],
        {"expected_pairing_version": expected_version},
        planner_headers,
    )
    data = validate_success(res, 200)
    assert data["state"] == "AWARDED", f"award response state must be AWARDED, got {data['state']!r}"
    assert data["version"] == expected_version + 1, (
        f"version must advance by exactly one on award, "
        f"before={expected_version}, after={data['version']}"
    )
