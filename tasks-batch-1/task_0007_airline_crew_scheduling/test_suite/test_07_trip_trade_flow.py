"""TripTrade flow: non-linear branching (PROPOSED→COUNTERSIGNED/REJECTED/WITHDRAWN),
reject undefined from COUNTERSIGNED, and approve-step pairing-overlap behavior.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    setup_clean_world,
    setup_two_crew_with_confirmed_assignments,
    setup_trip_trade_in_state,
    get_assignment,
    get_trip_trade,
    create_trip_trade_payload,
    make_crew_member_headers,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# Branching from PROPOSED: reject (counterparty)
# ---------------------------------------------------------------------

def test_trip_trade_reject_from_proposed_by_counterparty(api):
    """PRD §3.5: "From `PROPOSED` the counterparty (whose `X-User-ID` must match
    the trade's `counterparty_id`) may either countersign — moving `state` to
    `COUNTERSIGNED`, gated on both Assignments still being in `SCHEDULED` or
    `CONFIRMED` — or reject the trade outright, moving `state` to `REJECTED`
    and capturing the supplied `reason` into the trade's `rejection_reason`
    field."

    Design: Difficulty/non_linear_state_machine/trip_trade_branching_propose_countersign_or_reject
    """
    cm_a, cm_b, _pa, _pb, a_a, a_b, trade = setup_trip_trade_in_state("PROPOSED")
    res = api.reject_trip_trade(
        trade["id"], {"reason": "schedule conflict"}, make_crew_member_headers(cm_b["id"])
    )
    data = validate_success(res, 200)
    assert data["state"] == "REJECTED", (
        f"trade must transition to REJECTED, got {data['state']!r}"
    )
    assert data["rejection_reason"] == "schedule conflict", (
        f"rejection_reason must capture supplied reason, got {data['rejection_reason']!r}"
    )
    # The original assignments are unchanged.
    a_a_after = get_assignment(a_a["id"])
    a_b_after = get_assignment(a_b["id"])
    assert a_a_after["state"] == "CONFIRMED"
    assert a_b_after["state"] == "CONFIRMED"


# ---------------------------------------------------------------------
# Reject from COUNTERSIGNED is undefined → ERR_INVALID_STATE
# ---------------------------------------------------------------------

def test_trip_trade_reject_from_countersigned_returns_invalid_state(api):
    """PRD §2.9: "State eligibility: the target resource must currently be in
    a state from which the requested transition is defined (else `ERR_INVALID_STATE`)."
    PRD §3.5: "From `PROPOSED` the counterparty (whose `X-User-ID` must match
    the trade's `counterparty_id`) may either countersign [...] or reject the
    trade outright, moving `state` to `REJECTED` and capturing the supplied
    `reason` into the trade's `rejection_reason` field."

    Design: Corner/state_machines/trip_trade_reject_from_countersigned_returns_invalid_state
    """
    cm_a, cm_b, _pa, _pb, _aa, _ab, trade = setup_trip_trade_in_state("COUNTERSIGNED")
    assert trade["state"] == "COUNTERSIGNED"
    res = api.reject_trip_trade(
        trade["id"], {"reason": "changed mind"}, make_crew_member_headers(cm_b["id"])
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ---------------------------------------------------------------------
# Approve-step pairing-overlap behavior
# ---------------------------------------------------------------------

def test_trip_trade_approve_succeeds_when_no_overlap_after_swap(api, ops_headers):
    """PRD §2.12: "Trip-trade pairing-overlap uses **half-open** intervals:
    two duty windows where one ends exactly when the other begins (end_A
    equals start_B) are permitted as back-to-back, while end_A strictly
    greater than start_B is a conflict."
    PRD §3.6: "Specifically, duty-window intervals use **half-open** semantics
    on `[scheduled_start_utc, scheduled_end_utc)`: two windows where one ends
    exactly when the other begins (the prior window's end equals the next
    window's start) are permitted as back-to-back, while a prior window whose
    end is strictly later than the next window's start is a conflict."

    The two pairings span different days (2026-06-02 vs 2026-06-03) and each
    crew member retains only one assignment after the swap, so the overlap
    check passes and approval succeeds.

    Design: Difficulty/resource_temporal_overlap/trip_trade_pairing_overlap_half_open_interval
    """
    _cm_a, _cm_b, _pa, _pb, _aa, _ab, trade = setup_trip_trade_in_state("COUNTERSIGNED")
    res = api.approve_trip_trade(trade["id"], ops_headers)
    data = validate_success(res, 200)
    assert data["state"] == "APPROVED", (
        f"trade with no post-swap overlap must transition to APPROVED, got {data['state']!r}"
    )
