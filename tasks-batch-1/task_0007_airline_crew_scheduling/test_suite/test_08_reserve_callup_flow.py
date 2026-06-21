"""Reserve-callup chain: DECLINE creates a new OFFERED callup for the next
candidate; an empty candidate set raises ERR_NO_RESERVE_AVAILABLE; decline on
an already-ACCEPTED callup is an invalid transition.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    setup_clean_world,
    setup_sick_call_with_reserve_offered,
    create_crew_member,
    create_pairing,
    add_revenue_leg,
    open_bidding,
    submit_bid,
    award_pairing,
    confirm_assignment,
    first_assignment_for,
    report_sick_call,
    list_reserve_callups_for,
    get_sick_call,
    make_crew_member_headers,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# Decline → next OFFERED with callup_sequence + 1
# ---------------------------------------------------------------------

def test_reserve_decline_creates_next_offered_callup(api):
    """PRD §3.4: "If they decline, the current ReserveCallup moves from `OFFERED`
    to `DECLINED`, and the system immediately mints the next ReserveCallup
    with `callup_sequence` set to the prior sequence plus one, `state`
    `OFFERED`, and `selected_reserve_id` chosen by re-running the
    reserve-selector policy with the declining crew member excluded from the
    candidate pool."

    Design: Difficulty/non_linear_state_machine/reserve_callup_cyclic_decline_offer_loop
    """
    cm_l, cm_r1, _pairing, sick_call, callup1, _a_orig, cm_r2 = (
        setup_sick_call_with_reserve_offered(add_extra_reserve=True)
    )
    assert cm_r2 is not None, "test requires a second reserve"
    # Decline the first callup.
    res = api.decline_reserve_callup(callup1["id"], make_crew_member_headers(cm_r1["id"]))
    declined = validate_success(res, 200)
    assert declined["state"] == "DECLINED", (
        f"declined callup must move to DECLINED, got {declined['state']!r}"
    )
    # System must have minted a second ReserveCallup OFFERED to CM_R2.
    callups = list_reserve_callups_for(sick_call["id"])
    by_seq = sorted(callups, key=lambda c: c["callup_sequence"])
    assert len(by_seq) == 2, (
        f"after decline there must be exactly two ReserveCallups, got {len(by_seq)}"
    )
    assert by_seq[0]["callup_sequence"] == 1 and by_seq[0]["state"] == "DECLINED"
    assert by_seq[1]["callup_sequence"] == 2 and by_seq[1]["state"] == "OFFERED"
    assert by_seq[1]["selected_reserve_id"] == cm_r2["id"], (
        f"second callup must target the next reserve (CM_R2), "
        f"got selected_reserve_id={by_seq[1]['selected_reserve_id']!r}"
    )
    # SickCall remains ACKNOWLEDGED (not yet closed).
    sc_after = get_sick_call(sick_call["id"])
    assert sc_after["state"] == "ACKNOWLEDGED", (
        f"SickCall must stay ACKNOWLEDGED after decline, got {sc_after['state']!r}"
    )


# ---------------------------------------------------------------------
# Empty candidate set on acknowledge → ERR_NO_RESERVE_AVAILABLE
# ---------------------------------------------------------------------

def test_acknowledge_with_no_eligible_reserves_returns_no_reserve_available(
    api, planner_headers, ops_headers
):
    """PRD §3.4: "If no candidate survives the filter, the operation is
    rejected with `ERR_NO_RESERVE_AVAILABLE` (HTTP 422). The same exhaustion
    error is raised when the total number of callup attempts for a single
    SickCall would exceed five — that is, `callup_sequence` cannot grow
    beyond 5."

    Design: Difficulty/boundary_precision_check/no_eligible_reserve_empty_set_on_callup
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    # Lineholder CAPTAIN — needs replacement.
    cm_l = create_crew_member(
        employee_code="AB0110", seniority_number=110, line_type="LINEHOLDER", rank="CAPTAIN"
    )
    # Only an FO reserve exists — not eligible for a CAPTAIN seat.
    _cm_fo = create_crew_member(
        employee_code="AB0111", seniority_number=111, line_type="RESERVE", rank="FIRST_OFFICER"
    )
    pairing = create_pairing(pairing_code="P-2026-110")
    add_revenue_leg(pairing["id"])
    open_bidding(pairing["id"])
    submit_bid(pairing["id"], cm_l, requested_seat="CAPTAIN")
    set_clock("2026-06-01T12:00:01Z")
    award_pairing(pairing["id"])
    a_orig = first_assignment_for(pairing["id"], cm_l["id"])
    confirm_assignment(a_orig["id"], cm_l)
    sc = report_sick_call(a_orig["id"], cm_l)
    res = api.acknowledge_sick_call(sc["id"], ops_headers)
    validate_error(res, "ERR_NO_RESERVE_AVAILABLE", expected_status=422)
    # SickCall remains REPORTED (acknowledge failed).
    sc_after = get_sick_call(sc["id"])
    assert sc_after["state"] == "REPORTED", (
        f"failed acknowledge must leave SickCall in REPORTED, got {sc_after['state']!r}"
    )


# ---------------------------------------------------------------------
# Decline on an already-ACCEPTED ReserveCallup → ERR_INVALID_STATE
# ---------------------------------------------------------------------

def test_decline_on_accepted_reserve_callup_returns_invalid_state(api):
    """PRD §2.9: "State eligibility: the target resource must currently be in
    a state from which the requested transition is defined (else `ERR_INVALID_STATE`)."
    PRD §3.4: "If they decline, the current ReserveCallup moves from `OFFERED`
    to `DECLINED`".

    Design: Difficulty/cross_entity_state_dependency/reserve_callup_accept_requires_sickcall_acknowledged_pair_reservecallup_sickcall
    """
    cm_l, cm_r, _pairing, sick_call, callup, _a_orig, _cm_r2 = (
        setup_sick_call_with_reserve_offered()
    )
    # First, the reserve accepts.
    acc = api.accept_reserve_callup(callup["id"], make_crew_member_headers(cm_r["id"]))
    acc_data = validate_success(acc, 200)
    assert acc_data["state"] == "ACCEPTED"
    # SickCall has cascaded to CLOSED.
    sc_after = get_sick_call(sick_call["id"])
    assert sc_after["state"] == "CLOSED"
    # Now decline the same callup — its state is ACCEPTED, decline is undefined.
    res = api.decline_reserve_callup(callup["id"], make_crew_member_headers(cm_r["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
