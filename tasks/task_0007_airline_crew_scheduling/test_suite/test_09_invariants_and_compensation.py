"""Compensating-action invariants: trip-trade execute preserves the count of
non-terminal Assignments per Pairing, and reserve-callup accept preserves the
count of non-terminal Captain Assignments on the orphaned Pairing.
"""
from test_helpers import (
    validate_success,
    setup_sick_call_with_reserve_offered,
    setup_trip_trade_in_state,
    get_assignment,
    get_trip_trade,
    list_assignments_for,
    make_crew_member_headers,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# TripTrade execute conserves filled-seat count across pairings
# ---------------------------------------------------------------------

def test_trip_trade_execute_conserves_filled_seats(api, planner_headers, ops_headers):
    """PRD §3.5: "On success the swap fires atomically: the initiator's
    original Assignment cascades to `RELEASED`; the counterparty's original
    Assignment cascades to `RELEASED`; two new Assignments are created in
    `state` `CONFIRMED` with `source` `TRIP_TRADE`, each carrying the swapped
    `pairing_id` with the original seat, and `crew_member_id` set to the new
    owner; and the TripTrade's `state` flips to `EXECUTED`."

    Design: Difficulty/compensating_invariant/trip_trade_execute_conserves_total_filled_seats_across_pairings
    """
    cm_a, cm_b, pa, pb, a_a, a_b, trade = setup_trip_trade_in_state("APPROVED")
    # Pre-execute snapshot: each pairing has exactly one CONFIRMED Captain
    # Assignment, totalling 2 non-terminal Captain assignments across both
    # pairings.
    pre_a = [
        a for a in list_assignments_for(pa["id"], cm_a["id"])
        if a["state"] in ("SCHEDULED", "CONFIRMED", "ACTIVE")
    ]
    pre_b = [
        a for a in list_assignments_for(pb["id"], cm_b["id"])
        if a["state"] in ("SCHEDULED", "CONFIRMED", "ACTIVE")
    ]
    assert len(pre_a) == 1 and len(pre_b) == 1

    # Execute the trade.
    res = api.execute_trip_trade(
        trade["id"],
        {"expected_trip_trade_version": trade["version"]},
        ops_headers,
    )
    data = validate_success(res, 200)
    assert data["state"] == "EXECUTED", (
        f"executed trade must transition to EXECUTED, got {data['state']!r}"
    )

    # Originals released.
    a_a_after = get_assignment(a_a["id"])
    a_b_after = get_assignment(a_b["id"])
    assert a_a_after["state"] == "RELEASED"
    assert a_b_after["state"] == "RELEASED"

    # New CONFIRMED assignments on each pairing: cm_b now owns one on pa,
    # cm_a now owns one on pb.
    new_on_pa = list_assignments_for(pa["id"], cm_b["id"])
    new_on_pb = list_assignments_for(pb["id"], cm_a["id"])
    new_on_pa_nt = [a for a in new_on_pa if a["state"] in ("SCHEDULED", "CONFIRMED", "ACTIVE")]
    new_on_pb_nt = [a for a in new_on_pb if a["state"] in ("SCHEDULED", "CONFIRMED", "ACTIVE")]
    assert len(new_on_pa_nt) == 1, (
        f"P_A must still have exactly one non-terminal Captain Assignment after "
        f"the swap, got {len(new_on_pa_nt)}"
    )
    assert new_on_pa_nt[0]["state"] == "CONFIRMED"
    assert new_on_pa_nt[0]["source"] == "TRIP_TRADE"
    assert len(new_on_pb_nt) == 1, (
        f"P_B must still have exactly one non-terminal Captain Assignment after "
        f"the swap, got {len(new_on_pb_nt)}"
    )
    assert new_on_pb_nt[0]["state"] == "CONFIRMED"
    assert new_on_pb_nt[0]["source"] == "TRIP_TRADE"


# ---------------------------------------------------------------------
# Reserve-accept conserves filled-seat count on the orphaned pairing
# ---------------------------------------------------------------------

def test_reserve_accept_conserves_filled_captain_seats_on_pairing(api):
    """PRD §3.4: "On success a chain of cascades fires atomically: the original
    Assignment moves from `CONFIRMED` to `RECOVERED`; a replacement Assignment
    is created in `state` `CONFIRMED` with `source` `RESERVE_CALLUP`,
    `crew_member_id` set to the reserve's id (i.e., to `selected_reserve_id`),
    and `seat` copied from the original Assignment".

    Design: Difficulty/compensating_invariant/reserve_callup_accept_conserves_filled_captain_seats_on_pairing
    """
    cm_l, cm_r, pairing, _sc, callup, a_orig, _cm_r2 = (
        setup_sick_call_with_reserve_offered()
    )
    # Pre-accept: one non-terminal Captain Assignment (CM_L's CONFIRMED one).
    pre_l = [
        a for a in list_assignments_for(pairing["id"], cm_l["id"])
        if a["state"] in ("SCHEDULED", "CONFIRMED", "ACTIVE")
    ]
    assert len(pre_l) == 1 and pre_l[0]["state"] == "CONFIRMED"

    res = api.accept_reserve_callup(callup["id"], make_crew_member_headers(cm_r["id"]))
    validate_success(res, 200)

    # Original RECOVERED, removed from non-terminal set.
    a_orig_after = get_assignment(a_orig["id"])
    assert a_orig_after["state"] == "RECOVERED"

    # Reserve's replacement is the new sole non-terminal Captain Assignment.
    post_l = [
        a for a in list_assignments_for(pairing["id"], cm_l["id"])
        if a["state"] in ("SCHEDULED", "CONFIRMED", "ACTIVE")
    ]
    post_r = [
        a for a in list_assignments_for(pairing["id"], cm_r["id"])
        if a["state"] in ("SCHEDULED", "CONFIRMED", "ACTIVE")
    ]
    assert len(post_l) == 0, (
        f"CM_L must have zero non-terminal Assignments on this pairing post-accept, got {len(post_l)}"
    )
    assert len(post_r) == 1, (
        f"CM_R must hold exactly one non-terminal Assignment on this pairing post-accept, "
        f"got {len(post_r)}"
    )
    assert post_r[0]["state"] == "CONFIRMED"
    assert post_r[0]["seat"] == "CAPTAIN", (
        f"replacement Assignment must carry the original CAPTAIN seat, "
        f"got {post_r[0]['seat']!r}"
    )
    # Invariant: total non-terminal Captain Assignments on this pairing remains 1
    # (= required_captains).
    total_nt = len(post_l) + len(post_r)
    assert total_nt == pairing["required_captains"], (
        f"non-terminal Captain Assignment count must equal required_captains "
        f"({pairing['required_captains']}), got {total_nt}"
    )
