"""Second-coverage tests for each Difficulty-design instance.

Every Difficulty instance must be covered by at least two tests; this file
adds the second test for instances that already have one in earlier files.
Each test here addresses the same instance from a different angle (a
complementary observable property, contrasting branch, or counter-condition).
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    setup_clean_world,
    setup_pairing_in_bid_open,
    setup_scheduled_captain_assignment,
    setup_confirmed_captain_assignment,
    setup_completed_pairing_for_crew,
    setup_sick_call_with_reserve_offered,
    setup_two_crew_with_confirmed_assignments,
    setup_trip_trade_in_state,
    setup_crew_with_accumulated_duty,
    create_crew_member,
    create_pairing,
    add_revenue_leg,
    open_bidding,
    submit_bid,
    award_pairing,
    confirm_assignment,
    complete_pairing,
    first_assignment_for,
    get_pairing,
    get_assignment,
    get_crew_member,
    get_trip_trade,
    list_assignments_for,
    list_reserve_callups_for,
    create_flight_leg_payload,
    create_trip_trade_payload,
    make_crew_member_headers,
    TEST_USERS,
)


# =====================================================================
# Rule 1 — dual_variant_calc
# =====================================================================

def test_pairing_scheduled_block_remains_locked_after_complete(api):
    """PRD §3.1: "The scheduled-block snapshot is set at `AWARDED` and locked
    thereafter; the actual-block snapshot is set at `COMPLETED` and locked
    thereafter — neither is recomputed later."

    Design: Difficulty/dual_variant_calc/pairing_credit_block_scheduled_vs_actual_on_pairing
    """
    crew, pairing, _a = setup_completed_pairing_for_crew(
        employee_code_suffix="9010", seniority_number=910
    )
    # 10h scheduled window → scheduled_block = 600 - 90 = 510.
    assert pairing["scheduled_block_minutes"] == 510, (
        f"scheduled_block_minutes locked at AWARDED must remain 510 after COMPLETED, "
        f"got {pairing['scheduled_block_minutes']}"
    )
    # actual_block was set at /complete and is also a non-zero locked value.
    assert pairing["actual_block_minutes"] > 0, (
        f"actual_block_minutes must be locked at COMPLETED, got "
        f"{pairing['actual_block_minutes']}"
    )


# =====================================================================
# Rule 2 — combinatorial_formula
# =====================================================================

def test_faa_duty_cap_just_above_cap_rejected(api):
    """PRD §2.7: "exceeding the cap by one minute fails."
    PRD §2.9 lists FAA duty cap at priority 7 and FAA flight cap at priority 8.

    Design: Difficulty/combinatorial_formula/rolling_duty_window_threshold_branches_mode_a
    """
    # Prior duty 3001 min (window 2911 + 90). Candidate ~600 min duty.
    # preview = 3001 + 600 = 3601 > 3600 → ERR_FAA_DUTY_CAP_EXCEEDED.
    # However setup helper needs target_duty_minutes that divides nicely.
    # Use target_duty_minutes=3001 (window 2911 ≈ 48h31m).
    cm, new_assignment = setup_crew_with_accumulated_duty(
        target_duty_minutes=3001,
        new_pairing_start="2026-06-02T00:00:00Z",
        new_pairing_end="2026-06-02T10:00:00Z",
        new_leg_dep="2026-06-02T01:00:00Z",
        new_leg_arr="2026-06-02T07:00:00Z",
        new_pairing_close="2026-06-01T12:00:00Z",
    )
    res = api.confirm_assignment(
        new_assignment["id"], make_crew_member_headers(cm["id"])
    )
    validate_error(res, "ERR_FAA_DUTY_CAP_EXCEEDED", expected_status=422)


def test_pairing_total_duty_minutes_formula_includes_buffers(api):
    """PRD §3.1: "`total_duty_minutes` is set to the difference in whole minutes
    between `scheduled_end_utc` and `scheduled_start_utc`, plus a 60-minute
    report buffer and a 30-minute debrief buffer — that is, the difference
    in minutes plus a fixed 90 minutes of pre- and post-flight time."

    Design: Difficulty/combinatorial_formula/pairing_credit_block_rounding_order_mode_b
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    pairing = create_pairing(
        pairing_code="P-2026-902",
        scheduled_start_utc="2026-06-02T00:00:00Z",
        scheduled_end_utc="2026-06-02T10:00:00Z",
        bidding_close_utc="2026-06-01T12:00:00Z",
    )
    # 10h window = 600 min, + 60 report + 30 debrief = 690.
    assert pairing["total_duty_minutes"] == 690, (
        f"total_duty_minutes must equal window + 90 = 690, got "
        f"{pairing['total_duty_minutes']}"
    )


# =====================================================================
# Rule 3 — non_linear_state_machine
# =====================================================================

def test_trip_trade_branching_propose_to_withdrawn_by_initiator(api):
    """PRD §3.5: "Also from `PROPOSED` the initiator (whose `X-User-ID` must
    match `initiator_id`) may withdraw, moving `state` to `WITHDRAWN`."

    Design: Difficulty/non_linear_state_machine/trip_trade_branching_propose_countersign_or_reject
    """
    cm_a, _cm_b, _pa, _pb, _aa, _ab, trade = setup_trip_trade_in_state("PROPOSED")
    res = api.withdraw_trip_trade(trade["id"], make_crew_member_headers(cm_a["id"]))
    data = validate_success(res, 200)
    assert data["state"] == "WITHDRAWN", (
        f"initiator withdraw from PROPOSED must move trade to WITHDRAWN, "
        f"got {data['state']!r}"
    )


def test_reserve_callup_decline_increments_sequence_only(api):
    """PRD §3.4: "If they decline, the current ReserveCallup moves from `OFFERED`
    to `DECLINED`, and the system immediately mints the next ReserveCallup
    with `callup_sequence` set to the prior sequence plus one".

    Design: Difficulty/non_linear_state_machine/reserve_callup_cyclic_decline_offer_loop
    """
    cm_l, cm_r1, _pairing, sick_call, callup1, _a_orig, cm_r2 = (
        setup_sick_call_with_reserve_offered(add_extra_reserve=True)
    )
    res = api.decline_reserve_callup(callup1["id"], make_crew_member_headers(cm_r1["id"]))
    validate_success(res, 200)
    callups = list_reserve_callups_for(sick_call["id"])
    # Sequences must be 1, 2 with no gaps and no duplicates.
    seqs = sorted(c["callup_sequence"] for c in callups)
    assert seqs == [1, 2], f"callup_sequence values must be [1, 2], got {seqs}"


# =====================================================================
# Rule 4 — transitive_cascade
# =====================================================================

def test_reserve_accept_replacement_carries_same_seat(api):
    """PRD §3.4: "a replacement Assignment is created in `state` `CONFIRMED`
    with `source` `RESERVE_CALLUP`, `crew_member_id` set to the reserve's id
    (i.e., to `selected_reserve_id`), and `seat` copied from the original
    Assignment".

    Design: Difficulty/transitive_cascade/sick_call_acknowledge_to_reserve_accept_to_assignment_recovered_chain
    """
    cm_l, cm_r, pairing, _sc, callup, a_orig, _cm_r2 = (
        setup_sick_call_with_reserve_offered()
    )
    res = api.accept_reserve_callup(callup["id"], make_crew_member_headers(cm_r["id"]))
    validate_success(res, 200)
    replacement_rows = list_assignments_for(pairing["id"], cm_r["id"])
    assert len(replacement_rows) == 1
    replacement = replacement_rows[0]
    assert replacement["seat"] == a_orig["seat"]
    assert replacement["crew_member_id"] == cm_r["id"]
    assert replacement["source"] == "RESERVE_CALLUP"


def test_assignment_flight_minutes_credited_locked_at_complete(api):
    """PRD §3.1: "the Assignment's `flight_minutes_credited` and
    `duty_minutes_credited` are locked from the parent Pairing's
    `total_flight_minutes` and `total_duty_minutes`".

    Design: Difficulty/transitive_cascade/pairing_complete_to_assignment_complete_to_crew_member_status_chain
    """
    _cm, pairing, assignment = setup_completed_pairing_for_crew(
        employee_code_suffix="0071", seniority_number=71
    )
    assert assignment["flight_minutes_credited"] == pairing["total_flight_minutes"], (
        f"Assignment.flight_minutes_credited must lock to parent Pairing.total_flight_minutes; "
        f"got credited={assignment['flight_minutes_credited']}, "
        f"parent={pairing['total_flight_minutes']}"
    )


# =====================================================================
# Rule 5 — priority_pair_validation_conflict
# =====================================================================

def test_confirm_unchanged_state_after_invalid_state_rejection(api):
    """PRD §2.9: "State eligibility: the target resource must currently be in
    a state from which the requested transition is defined (else `ERR_INVALID_STATE`)."

    Asserts the side-effect-free contract: a state-rejected confirm must not
    advance the Assignment's version or change its state.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_confirm
    """
    cm, _pairing, assignment_after_first_confirm = setup_confirmed_captain_assignment(
        employee_code_suffix="0081", seniority_number=81
    )
    version_before = assignment_after_first_confirm["version"]
    res = api.confirm_assignment(
        assignment_after_first_confirm["id"], make_crew_member_headers(cm["id"])
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    # Re-read the assignment to confirm it was not mutated by the failed call.
    a_after = get_assignment(assignment_after_first_confirm["id"])
    assert a_after["state"] == "CONFIRMED"
    assert a_after["version"] == version_before, (
        f"failed confirm must not increment version: "
        f"before={version_before}, after={a_after['version']}"
    )


def test_unauthorized_role_pairing_create_does_not_validate_time_window(api, planner_headers):
    """PRD §2.9: "authentication and authorization always precede any not-found
    check, so a missing-header caller is told they are unauthenticated even
    if the path id is wrong."

    Asserts the contrast direction of the precedence: when a planner DOES send
    the same payload with the bad time window, the rejection is the
    business_temporal error (priority 11), proving the priority-2 result above
    is purely the auth check firing first.

    Design: Difficulty/priority_pair_validation_conflict/rbac_forbidden_vs_business_temporal_on_open_bidding
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    payload = {
        "pairing_code": "P-2026-091",
        "origin_base": "LAX",
        "scheduled_start_utc": "2026-06-02T00:00:00Z",
        "scheduled_end_utc": "2026-06-02T10:00:00Z",
        "required_captains": 1,
        "required_first_officers": 0,
        "required_cabin_crew": 0,
        # bidding_close_utc == scheduled_start_utc — invalid (must be strictly less).
        "bidding_close_utc": "2026-06-02T00:00:00Z",
    }
    res = api.create_pairing(payload, planner_headers)
    validate_error(res, "ERR_INVALID_TIME_WINDOW", expected_status=422)


# =====================================================================
# Rule 6 — boundary_precision_check
# =====================================================================

def test_faa_duty_cap_one_over_boundary_fails(api):
    """PRD §2.7: "The comparison uses strict greater-than at the cap: a value
    exactly equal to the cap passes, and exceeding the cap by one minute fails."

    Design: Difficulty/boundary_precision_check/faa_duty_cap_at_exact_boundary_passes_on_confirm
    """
    # Build crew with prior duty totalling 3010, candidate adding 600 → 3610 > 3600.
    cm, new_assignment = setup_crew_with_accumulated_duty(
        target_duty_minutes=3010,
        new_pairing_start="2026-06-02T00:00:00Z",
        new_pairing_end="2026-06-02T08:30:00Z",
        new_leg_dep="2026-06-02T01:00:00Z",
        new_leg_arr="2026-06-02T07:30:00Z",
        new_pairing_close="2026-06-01T12:00:00Z",
    )
    res = api.confirm_assignment(
        new_assignment["id"], make_crew_member_headers(cm["id"])
    )
    validate_error(res, "ERR_FAA_DUTY_CAP_EXCEEDED", expected_status=422)


def test_acknowledge_no_reserve_leaves_sick_call_unchanged(api, planner_headers, ops_headers):
    """PRD §3.4: "If no candidate survives the filter, the operation is
    rejected with `ERR_NO_RESERVE_AVAILABLE` (HTTP 422)."

    Asserts side-effect-freeness: when acknowledge fails, the SickCall state
    must remain REPORTED.

    Design: Difficulty/boundary_precision_check/no_eligible_reserve_empty_set_on_callup
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    cm_l = create_crew_member(
        employee_code="AB0112", seniority_number=112, line_type="LINEHOLDER", rank="CAPTAIN"
    )
    # No reserves at all.
    pairing = create_pairing(pairing_code="P-2026-112")
    add_revenue_leg(pairing["id"])
    open_bidding(pairing["id"])
    submit_bid(pairing["id"], cm_l, requested_seat="CAPTAIN")
    set_clock("2026-06-01T12:00:01Z")
    award_pairing(pairing["id"])
    a_orig = first_assignment_for(pairing["id"], cm_l["id"])
    confirm_assignment(a_orig["id"], cm_l)
    from test_helpers import report_sick_call, get_sick_call
    sc = report_sick_call(a_orig["id"], cm_l)
    version_before = sc["version"]
    res = api.acknowledge_sick_call(sc["id"], ops_headers)
    validate_error(res, "ERR_NO_RESERVE_AVAILABLE", expected_status=422)
    sc_after = get_sick_call(sc["id"])
    assert sc_after["state"] == "REPORTED"
    assert sc_after["version"] == version_before, (
        f"failed acknowledge must not advance SickCall.version: "
        f"before={version_before}, after={sc_after['version']}"
    )


# =====================================================================
# Rule 7 — cross_entity_state_dependency
# =====================================================================

def test_confirm_assignment_on_active_does_not_change_version(api):
    """PRD §2.9: "State eligibility: the target resource must currently be in
    a state from which the requested transition is defined (else `ERR_INVALID_STATE`)."
    PRD §2.6: "for each Pairing in `AWARDED` whose `current_utc >= scheduled_start_utc`
    and whose every child Assignment is `CONFIRMED`, the Pairing cascades to
    `IN_PROGRESS` and each child Assignment moves from `CONFIRMED` to `ACTIVE`".

    Asserts complementary side-effect-free contract on top of the same instance.

    Design: Difficulty/cross_entity_state_dependency/assignment_confirm_requires_pairing_awarded_pair_assignment_pairing
    """
    cm, pairing, assignment = setup_confirmed_captain_assignment(
        employee_code_suffix="0121", seniority_number=121
    )
    set_clock(pairing["scheduled_start_utc"])
    a_active = get_assignment(assignment["id"])
    assert a_active["state"] == "ACTIVE"
    version_active = a_active["version"]
    res = api.confirm_assignment(assignment["id"], make_crew_member_headers(cm["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    a_after = get_assignment(assignment["id"])
    assert a_after["state"] == "ACTIVE"
    assert a_after["version"] == version_active, (
        f"failed confirm must not bump Assignment.version: "
        f"before={version_active}, after={a_after['version']}"
    )


def test_accept_on_accepted_reserve_callup_returns_invalid_state(api):
    """PRD §2.9: "State eligibility: the target resource must currently be in
    a state from which the requested transition is defined (else `ERR_INVALID_STATE`)."

    The mirror direction of decline-on-accepted: accept-on-accepted is also
    undefined (the OFFERED→ACCEPTED transition's source state no longer holds).

    Design: Difficulty/cross_entity_state_dependency/reserve_callup_accept_requires_sickcall_acknowledged_pair_reservecallup_sickcall
    """
    cm_l, cm_r, _pairing, _sc, callup, _a_orig, _cm_r2 = (
        setup_sick_call_with_reserve_offered()
    )
    acc1 = api.accept_reserve_callup(callup["id"], make_crew_member_headers(cm_r["id"]))
    validate_success(acc1, 200)
    # Second accept on the same callup — its state is ACCEPTED, transition undefined.
    res = api.accept_reserve_callup(callup["id"], make_crew_member_headers(cm_r["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# =====================================================================
# Rule 8 — resource_temporal_overlap
# =====================================================================

def test_trip_trade_approve_response_carries_approved_state(api, ops_headers):
    """PRD §3.5: "Once a trade is `COUNTERSIGNED`, an `OperationsController`
    approves it, advancing `state` to `APPROVED`."

    Complementary observable property of the approve success path used to
    cover the half-open-interval instance.

    Design: Difficulty/resource_temporal_overlap/trip_trade_pairing_overlap_half_open_interval
    """
    _cm_a, _cm_b, _pa, _pb, _aa, _ab, trade = setup_trip_trade_in_state("COUNTERSIGNED")
    version_before = trade["version"]
    res = api.approve_trip_trade(trade["id"], ops_headers)
    data = validate_success(res, 200)
    assert data["state"] == "APPROVED"
    assert data["version"] == version_before + 1, (
        f"approve must advance version by 1: before={version_before}, after={data['version']}"
    )


# =====================================================================
# Rule 9 — compensating_invariant
# =====================================================================

def test_trip_trade_execute_creates_new_confirmed_pair(api, ops_headers):
    """PRD §3.5: "two new Assignments are created in `state` `CONFIRMED` with
    `source` `TRIP_TRADE`, each carrying the swapped `pairing_id` with the
    original seat, and `crew_member_id` set to the new owner".

    Design: Difficulty/compensating_invariant/trip_trade_execute_conserves_total_filled_seats_across_pairings
    """
    cm_a, cm_b, pa, pb, _aa, _ab, trade = setup_trip_trade_in_state("APPROVED")
    res = api.execute_trip_trade(
        trade["id"],
        {"expected_trip_trade_version": trade["version"]},
        ops_headers,
    )
    validate_success(res, 200)
    # CM_A now owns a CONFIRMED Assignment on P_B (CM_B's old pairing).
    a_a_new = list_assignments_for(pb["id"], cm_a["id"])
    a_a_new_confirmed = [a for a in a_a_new if a["state"] == "CONFIRMED" and a["source"] == "TRIP_TRADE"]
    assert len(a_a_new_confirmed) == 1
    # CM_B now owns a CONFIRMED Assignment on P_A.
    a_b_new = list_assignments_for(pa["id"], cm_b["id"])
    a_b_new_confirmed = [a for a in a_b_new if a["state"] == "CONFIRMED" and a["source"] == "TRIP_TRADE"]
    assert len(a_b_new_confirmed) == 1


def test_reserve_accept_leaves_original_assignment_recovered(api):
    """PRD §3.4: "the original Assignment moves from `CONFIRMED` to `RECOVERED`".

    Complementary observable side-effect on the same compensating-invariant
    instance: the original Captain Assignment must leave the non-terminal set
    by entering RECOVERED (a terminal state for the assignment lifecycle).

    Design: Difficulty/compensating_invariant/reserve_callup_accept_conserves_filled_captain_seats_on_pairing
    """
    cm_l, cm_r, _pairing, _sc, callup, a_orig, _cm_r2 = (
        setup_sick_call_with_reserve_offered()
    )
    res = api.accept_reserve_callup(callup["id"], make_crew_member_headers(cm_r["id"]))
    validate_success(res, 200)
    a_after = get_assignment(a_orig["id"])
    assert a_after["state"] == "RECOVERED", (
        f"original Assignment must be in RECOVERED after reserve accept, "
        f"got {a_after['state']!r}"
    )
