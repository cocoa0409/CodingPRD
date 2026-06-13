"""Second-observable corroboration for each depth (difficulty) instance.

Each test here re-exercises a difficulty instance's scenario but pins a different
observable from that instance's assertion set than the primary test in files
01-10, so every difficulty instance carries at least two independent assertions.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_driver_headers, make_rider_headers, make_program_admin_headers,
    setup_active_pool, setup_completed_single_rider_trip, setup_rider_with_reliability,
    create_trip, create_reservation,
)

PA = make_program_admin_headers()


def _board_checkin_depart_complete(api, trip_id, drv_id, res_ids, hov):
    get_success_data(api.open_boarding_trip(trip_id, make_driver_headers(drv_id)))
    for rid in res_ids:
        get_success_data(api.check_in_reservation(rid, make_driver_headers(drv_id)))
    get_success_data(api.depart_trip(trip_id, make_driver_headers(drv_id)))
    return get_success_data(api.complete_trip(trip_id, {"hov_lane_used": hov},
                                              make_driver_headers(drv_id)))


def test_estimate_cost_share_reflects_forward_looking_occupancy(api):
    """PRD §3.7: "For the estimate, N is forward-looking: the sum of `seat_count`
    over the trip's reservations that are `RESERVED` or `CHECKED_IN`, including the
    reservation being created."

    R1 reserving first sees forward N=1 (factor 1.00) so estimate==3200; R2 reserving
    second sees forward N=2 (factor 1.00) so estimate==1600.

    Design: Difficulty/dual_variant_calc/cost_share_estimate_vs_final_diverges_on_no_show
    """
    ctx = setup_active_pool(api=api, base_cost_cents=2000, per_mile_cents=120,
                            seed_rider_name="Rae One", seed_rider_wallet=10000)
    prog_id, drv_id, pool_id = ctx["program_id"], ctx["driver_id"], ctx["pool_id"]
    r1 = ctx["seed"]
    r2 = get_success_data(api.create_member(
        {"employer_program_id": prog_id, "full_name": "Rae Two", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 10000}, PA))
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0, hov_lane_used=True)
    res1 = get_success_data(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": r1["id"],
         "expected_trip_version": trip["version"], "seat_count": 1, "pay_now": True},
        make_rider_headers(r1["id"])))
    trip_v1 = get_success_data(api.get_trip(trip["id"], make_driver_headers(drv_id)))["version"]
    res2 = get_success_data(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": r2["id"],
         "expected_trip_version": trip_v1, "seat_count": 1, "pay_now": True},
        make_rider_headers(r2["id"])))
    assert res1["estimate_cost_share_cents"] == 3200
    assert res2["estimate_cost_share_cents"] == 1600


def test_provisional_reliability_strictly_exceeds_confirmed_while_pending(api):
    """PRD §3.8: "The provisional variant is never persisted and diverges upward from
    the confirmed score while pending reservations exist; it is surfaced only through
    the reliability read when the `mode` query value is `provisional`."

    The persisted (confirmed) score after one NO_SHOW is 85.0; with one outstanding
    RESERVED reservation the provisional read is strictly higher.

    Design: Difficulty/dual_variant_calc/reliability_provisional_vs_confirmed_diverges_on_pending
    """
    ctx = setup_rider_with_reliability(target_no_shows=1, api=api, rider_wallet=50000)
    prog_id, drv_id, rider_id = ctx["program_id"], ctx["driver_id"], ctx["rider_id"]
    veh = get_success_data(api.create_vehicle(
        {"owner_member_id": drv_id, "plate": "VAN-2", "seat_capacity": 6},
        make_driver_headers(drv_id)))
    pool = get_success_data(api.create_pool(
        {"employer_program_id": prog_id, "driver_member_id": drv_id, "vehicle_id": veh["id"],
         "kind": "VANPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(drv_id)))
    get_success_data(api.create_membership(
        {"pool_id": pool["id"], "rider_member_id": rider_id, "expected_pool_version": pool["version"]},
        make_rider_headers(rider_id)))
    get_success_data(api.activate_pool(pool["id"], make_driver_headers(drv_id)))
    trip = create_trip(pool["id"], drv_id, api=api, departure_at="2026-08-01T15:00:00Z",
                       distance_miles=10.0)
    create_reservation(trip["id"], rider_id, trip["version"], api=api, seat_count=1)

    stored = get_success_data(api.get_member(rider_id, PA))["reliability_score"]
    provisional = validate_success(api.get_member_reliability(
        rider_id, make_rider_headers(rider_id), params={"mode": "provisional"}))
    assert stored == 85.0
    assert provisional["reliability_score"] > stored


def test_cost_share_mid_tier_factor_applies_at_three_seats(api):
    """PRD §3.7: "when N is exactly 3 the factor is 0.90".
    PRD §3.7: "This reservation's share is the per-seat raw amount multiplied by this
    reservation's `seat_count`, rounded half-up to whole cents exactly once."

    The third reservation on a 5000-cent trip sees forward-looking N=3 (tier 0.90)
    so its estimate is 5000*0.90/3 == 1500, a different tier branch than N>=4.

    Design: Difficulty/combinatorial_formula/cost_share_tiered_occupancy_nonlinear_mode_a
    """
    ctx = setup_active_pool(api=api, base_cost_cents=3000, per_mile_cents=100,
                            seed_rider_name="R1", seed_rider_wallet=50000)
    prog_id, drv_id, pool_id = ctx["program_id"], ctx["driver_id"], ctx["pool_id"]
    riders = [ctx["seed"]]
    for nm in ("R2", "R3"):
        riders.append(get_success_data(api.create_member(
            {"employer_program_id": prog_id, "full_name": nm, "home_zone": "Z-N",
             "work_zone": "Z-DT", "wallet_balance_cents": 50000}, PA)))
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=20.0)
    last_est = None
    cur_ver = trip["version"]
    for rider in riders:
        res = get_success_data(api.create_reservation(
            {"trip_id": trip["id"], "rider_member_id": rider["id"],
             "expected_trip_version": cur_ver, "seat_count": 1},
            make_rider_headers(rider["id"])))
        last_est = res["estimate_cost_share_cents"]
        cur_ver = get_success_data(api.get_trip(trip["id"], make_driver_headers(drv_id)))["version"]
    assert last_est == 1500, f"3rd reservation forward N=3 tier 0.90: 5000*0.9/3=1500, got {last_est}"


def test_subsidy_net_charge_is_final_cost_share_minus_subsidy(api):
    """PRD §3.7: "its `net_charge_cents` is set to the final cost-share minus the
    final subsidy floored at 0".

    With final cost-share 1505 and per-layer subsidy 1001, the net charge taken from
    the wallet is 504.

    Design: Difficulty/combinatorial_formula/subsidy_per_layer_rounding_order_mode_b
    """
    ctx = setup_active_pool(api=api, base_cost_cents=505, per_mile_cents=100,
                            hov_eligible=True, seed_rider_name="Rae", seed_rider_wallet=50000,
                            program_overrides={"hov_discount_pct": 0.50,
                                               "employer_match_pct": 0.33,
                                               "monthly_benefit_cap_cents": 100000,
                                               "subsidy_budget_cents": 1000000})
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0, hov_lane_used=True)
    res = get_success_data(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": rider["id"],
         "expected_trip_version": trip["version"], "seat_count": 1, "pay_now": True},
        make_rider_headers(rider["id"])))
    _board_checkin_depart_complete(api, trip["id"], drv_id, [res["id"]], True)
    final = get_success_data(api.get_reservation(res["id"], make_driver_headers(drv_id)))
    assert final["final_cost_share_cents"] == 1505
    assert final["net_charge_cents"] == 504


def test_no_show_settles_charged_payment_axis(api):
    """PRD §3.6: "if `payment_status` was `CHARGED`, the `estimate_cost_share_cents`
    is retained as a no-show penalty and `payment_status` becomes `SETTLED`,
    otherwise `payment_status` is left unchanged."

    A pay_now reservation that no-shows on depart keeps its money axis at SETTLED
    while the seat axis reads NO_SHOW.

    Design: Difficulty/non_linear_state_machine/reservation_parallel_status_axes_evolve_independently
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=50000)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    res = validate_success(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": rider["id"],
         "expected_trip_version": trip["version"], "seat_count": 1, "pay_now": True},
        make_rider_headers(rider["id"])), expected_status=201)
    get_success_data(api.open_boarding_trip(trip["id"], make_driver_headers(drv_id)))
    get_success_data(api.depart_trip(trip["id"], make_driver_headers(drv_id)))
    after = get_success_data(api.get_reservation(res["id"], make_driver_headers(drv_id)))
    assert after["reservation_status"] == "NO_SHOW"
    assert after["payment_status"] == "SETTLED"


def test_match_score_ranks_second_pool_lower_than_selected(api):
    """PRD §3.4: "Running the matcher advances an `OPEN` request to `MATCHED` by
    selecting the single best eligible pool."
    PRD §3.4: "On selection, the request's `matched_pool_id` is set to the chosen
    pool, its `match_score` is set to that pool's score, and the request moves to
    `MATCHED`."

    PoolA (seat_room 5) outscores PoolB (seat_room 2) so the first match selects
    PoolA at score 60.00.

    Design: Difficulty/non_linear_state_machine/matchrequest_cyclic_matched_to_open_revert
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 100000, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))

    def mk_member(name, **kw):
        p = {"employer_program_id": program["id"], "full_name": name, "home_zone": "Z-N",
             "work_zone": "Z-DT"}
        p.update(kw)
        return get_success_data(api.create_member(p, PA))

    drv_a = mk_member("DrvA", can_drive=True)
    drv_b = mk_member("DrvB", can_drive=True)
    f1, f2, f3 = mk_member("F1"), mk_member("F2"), mk_member("F3")
    rider = mk_member("Rae")
    veh_a = get_success_data(api.create_vehicle(
        {"owner_member_id": drv_a["id"], "plate": "VAN-A", "seat_capacity": 6},
        make_driver_headers(drv_a["id"])))
    veh_b = get_success_data(api.create_vehicle(
        {"owner_member_id": drv_b["id"], "plate": "VAN-B", "seat_capacity": 4},
        make_driver_headers(drv_b["id"])))

    def mk_pool(driver, veh):
        return get_success_data(api.create_pool(
            {"employer_program_id": program["id"], "driver_member_id": driver["id"],
             "vehicle_id": veh["id"], "kind": "VANPOOL", "origin_zone": "Z-N",
             "dest_zone": "Z-DT", "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
             "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(driver["id"])))

    pool_a = mk_pool(drv_a, veh_a)
    pool_b = mk_pool(drv_b, veh_b)
    get_success_data(api.create_membership(
        {"pool_id": pool_a["id"], "rider_member_id": f1["id"],
         "expected_pool_version": pool_a["version"]}, make_rider_headers(f1["id"])))
    get_success_data(api.create_membership(
        {"pool_id": pool_b["id"], "rider_member_id": f2["id"],
         "expected_pool_version": pool_b["version"]}, make_rider_headers(f2["id"])))
    pb_v1 = get_success_data(api.get_pool(pool_b["id"], make_rider_headers(f3["id"])))["version"]
    get_success_data(api.create_membership(
        {"pool_id": pool_b["id"], "rider_member_id": f3["id"],
         "expected_pool_version": pb_v1}, make_rider_headers(f3["id"])))
    get_success_data(api.activate_pool(pool_a["id"], make_driver_headers(drv_a["id"])))
    get_success_data(api.activate_pool(pool_b["id"], make_driver_headers(drv_b["id"])))

    mr = get_success_data(api.create_match_request(
        {"rider_member_id": rider["id"], "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "needed_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "earliest_departure_min": 480, "latest_departure_min": 600},
        make_rider_headers(rider["id"])))
    matched = validate_success(api.match_match_request(mr["id"], make_rider_headers(rider["id"])))
    assert matched["matched_pool_id"] == pool_a["id"]
    assert matched["match_score"] == 60.0


def test_trip_cancel_cascade_marks_each_reservation_cancelled(api):
    """PRD §3.5: "Cancelling from `SCHEDULED` cascades every `RESERVED` reservation
    to `CANCELLED`".

    Both pay_now reservations on the cancelled SCHEDULED trip read CANCELLED.

    Design: Difficulty/transitive_cascade/trip_cancel_cascade_depth4_subsidy_ledger
    """
    ctx = setup_active_pool(api=api, seed_rider_name="R1", seed_rider_wallet=50000)
    prog_id, drv_id, pool_id = ctx["program_id"], ctx["driver_id"], ctx["pool_id"]
    r1 = ctx["seed"]
    r2 = get_success_data(api.create_member(
        {"employer_program_id": prog_id, "full_name": "R2", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 50000}, PA))
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    res1 = create_reservation(trip["id"], r1["id"], trip["version"], api=api, seat_count=1, pay_now=True)
    trip_v1 = get_success_data(api.get_trip(trip["id"], make_driver_headers(drv_id)))["version"]
    res2 = create_reservation(trip["id"], r2["id"], trip_v1, api=api, seat_count=1, pay_now=True)
    get_success_data(api.cancel_trip(trip["id"], make_driver_headers(drv_id)))
    assert get_success_data(api.get_reservation(res1["id"], make_driver_headers(drv_id)))[
        "reservation_status"] == "CANCELLED"
    assert get_success_data(api.get_reservation(res2["id"], make_driver_headers(drv_id)))[
        "reservation_status"] == "CANCELLED"


def test_no_show_cascade_marks_reservation_no_show(api):
    """PRD §3.5: "every reservation still in `RESERVED` at that moment is cascaded to
    `NO_SHOW`, and each such no-show runs the no-show side effects below."

    Departing a BOARDING trip flips the lone RESERVED reservation to NO_SHOW.

    Design: Difficulty/transitive_cascade/no_show_cascade_depth3_reliability_recompute
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=50000)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    res = create_reservation(trip["id"], rider["id"], trip["version"], api=api, seat_count=1)
    get_success_data(api.open_boarding_trip(trip["id"], make_driver_headers(drv_id)))
    get_success_data(api.depart_trip(trip["id"], make_driver_headers(drv_id)))
    after = get_success_data(api.get_reservation(res["id"], make_driver_headers(drv_id)))
    assert after["reservation_status"] == "NO_SHOW"


def test_reserve_on_cancelled_trip_does_not_consume_a_seat(api):
    """PRD §2.8: "Sixth, the target resource's own state must permit the requested
    transition, or the request fails with `ERR_INVALID_STATE`."

    A reservation rejected by the state check on a CANCELLED trip never creates a
    row, so a follow-up read of the trip still shows seats_reserved 0.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reserve_terminal_trip
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=0)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    cancelled = validate_success(api.cancel_trip(trip["id"], make_driver_headers(drv_id)))
    validate_error(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": rider["id"],
         "expected_trip_version": cancelled["version"], "seat_count": 1, "pay_now": True},
        make_rider_headers(rider["id"])), ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_trip(trip["id"], make_driver_headers(drv_id)))
    assert after["seats_reserved"] == 0


def test_low_reliability_rider_score_is_fifty_five_after_three_no_shows(api):
    """PRD §3.8: "A `NO_SHOW` event contributes −15.0".
    PRD §3.8: "The raw score is 100 plus the sum of every event's `weight_delta`;
    that raw value is clamped to the range from 0.0 to 100.0 after all deltas are
    summed, and only then rounded half-up to one decimal place."

    Three realized NO_SHOWs leave the rider at 100 - 45 == 55.0, the precondition for
    the safety-beats-constraint conflict.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_reserve_low_reliability_full_trip
    """
    ctx = setup_rider_with_reliability(target_no_shows=3, api=api, rider_wallet=50000)
    member = get_success_data(api.get_member(ctx["rider_id"], PA))
    assert member["reliability_score"] == 55.0


def test_reservation_boundary_seventy_keeps_member_score_at_floor(api):
    """PRD §3.8: "A `NO_SHOW` event contributes −15.0".
    PRD §3.6: "A rider whose stored (confirmed) `reliability_score` is below 70.0 may
    not create a new reservation and is turned away with `ERR_RELIABILITY_TOO_LOW`."

    Exactly two NO_SHOWs put the confirmed score at the 70.0 floor, the admitting
    boundary of the reliability gate.

    Design: Difficulty/boundary_precision_check/reliability_floor_exact_70_admitted
    """
    ctx = setup_rider_with_reliability(target_no_shows=2, api=api, rider_wallet=50000)
    member = get_success_data(api.get_member(ctx["rider_id"], PA))
    assert member["reliability_score"] == 70.0


def test_complete_empty_trip_reaches_completed_terminal_state(api):
    """PRD §3.5: "Completing moves a trip from `IN_TRANSIT` to `COMPLETED`; this is
    the settlement event detailed in §3.6."

    A trip departed with zero checked-in riders still reaches COMPLETED.

    Design: Difficulty/boundary_precision_check/empty_completed_set_zero_division_guarded_on_complete
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=50000)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    get_success_data(api.open_boarding_trip(trip["id"], make_driver_headers(drv_id)))
    get_success_data(api.depart_trip(trip["id"], make_driver_headers(drv_id)))
    completed = validate_success(api.complete_trip(
        trip["id"], {"hov_lane_used": False}, make_driver_headers(drv_id)))
    assert completed["status"] == "COMPLETED"


def test_grh_approve_under_active_program_state_precondition(api):
    """PRD §3.1: "Freezing is permitted only when the program is currently `ACTIVE`,
    and unfreezing only when it is currently `FROZEN`; either transition increments
    the program's `version` by one."

    Freezing the reimbursing program is what makes the subsequent GRH approve fail
    its cross-entity gate; the frozen state is the asserted precondition.

    Design: Difficulty/cross_entity_state_dependency/grh_approve_requires_program_active_pair_grh_program
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 100000, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    frozen = validate_success(api.freeze_employer_program(program["id"], PA))
    assert frozen["status"] == "FROZEN"


def test_trip_window_overlap_leaves_only_one_trip_on_pool(api):
    """PRD §3.5: "its travel window, the half-open interval from `departure_at` up to
    but not including `departure_at` plus `duration_min`, must not overlap the window
    of any non-`CANCELLED` trip of that pool, with no buffer applied; an overlap is
    rejected with `ERR_TRIP_WINDOW_OVERLAP`."

    The rejected overlapping trip is never created, so the pool still lists exactly
    one trip.

    Design: Difficulty/resource_temporal_overlap/trip_window_half_open_no_buffer_on_pool
    """
    from test_helpers import validate_paginated
    ctx = setup_active_pool(api=api)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    create_trip(pool_id, drv_id, api=api, departure_at="2026-06-09T15:00:00Z",
                duration_min=40, distance_miles=10.0)
    validate_error(api.create_trip(
        {"pool_id": pool_id, "departure_at": "2026-06-09T15:39:00Z",
         "duration_min": 40, "distance_miles": 10.0}, make_driver_headers(drv_id)),
        ApiErrorId.ERR_TRIP_WINDOW_OVERLAP.value)
    trips, _meta = validate_paginated(api.list_trips(
        make_driver_headers(drv_id), params={"pool_id": pool_id}))
    assert len(trips) == 1


def test_rider_double_booked_does_not_create_second_reservation(api):
    """PRD §3.6: "the new reservation may not put the rider on two trips whose travel
    windows, each expanded on both sides by the rider buffer of fifteen minutes (a
    closed interval), overlap — a clash is rejected with `ERR_RIDER_DOUBLE_BOOKED`."

    The second (conflicting) reservation is rejected, so listing the rider's
    reservations returns only the first.

    Design: Difficulty/resource_temporal_overlap/rider_double_booked_buffered_closed_interval_on_member
    """
    from test_helpers import validate_paginated
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 100000, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))

    def mk_member(name, **kw):
        p = {"employer_program_id": program["id"], "full_name": name, "home_zone": "Z-N",
             "work_zone": "Z-DT"}
        p.update(kw)
        return get_success_data(api.create_member(p, PA))

    drv_a = mk_member("DrvA", can_drive=True)
    drv_b = mk_member("DrvB", can_drive=True)
    rider = mk_member("Rae", wallet_balance_cents=50000)

    def mk_pool_trip(driver, plate, dep):
        veh = get_success_data(api.create_vehicle(
            {"owner_member_id": driver["id"], "plate": plate, "seat_capacity": 6},
            make_driver_headers(driver["id"])))
        pool = get_success_data(api.create_pool(
            {"employer_program_id": program["id"], "driver_member_id": driver["id"],
             "vehicle_id": veh["id"], "kind": "VANPOOL", "origin_zone": "Z-N",
             "dest_zone": "Z-DT", "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
             "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(driver["id"])))
        get_success_data(api.create_membership(
            {"pool_id": pool["id"], "rider_member_id": rider["id"],
             "expected_pool_version": pool["version"]}, make_rider_headers(rider["id"])))
        get_success_data(api.activate_pool(pool["id"], make_driver_headers(driver["id"])))
        return create_trip(pool["id"], driver["id"], api=api, departure_at=dep,
                           duration_min=40, distance_miles=10.0)

    trip_a = mk_pool_trip(drv_a, "VAN-A", "2026-06-09T15:00:00Z")
    trip_b = mk_pool_trip(drv_b, "VAN-B", "2026-06-09T16:00:00Z")
    create_reservation(trip_a["id"], rider["id"], trip_a["version"], api=api, seat_count=1)
    validate_error(api.create_reservation(
        {"trip_id": trip_b["id"], "rider_member_id": rider["id"],
         "expected_trip_version": trip_b["version"], "seat_count": 1},
        make_rider_headers(rider["id"])), ApiErrorId.ERR_RIDER_DOUBLE_BOOKED.value)
    res_list, _meta = validate_paginated(api.list_reservations(
        make_rider_headers(rider["id"]), params={"rider_member_id": rider["id"]}))
    assert len(res_list) == 1


def test_seat_conservation_charged_amount_refunded_on_cancel(api):
    """PRD §3.6: "if `payment_status` was `CHARGED`, the `estimate_cost_share_cents`
    is refunded to the rider wallet and `payment_status` becomes `REFUNDED`".

    Cancelling the 2-seat pay_now reservation restores the rider wallet to its
    pre-reserve balance and moves the money axis to REFUNDED.

    Design: Difficulty/compensating_invariant/seat_conservation_reserve_then_cancel_leaves_seats_reserved
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=50000)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    res = create_reservation(trip["id"], rider["id"], trip["version"], api=api,
                             seat_count=2, pay_now=True)
    cancelled = validate_success(api.cancel_reservation(res["id"], make_rider_headers(rider["id"])))
    assert cancelled["payment_status"] == "REFUNDED"
    assert get_success_data(api.get_member(rider["id"], PA))["wallet_balance_cents"] == 50000


def test_subsidy_budget_conservation_no_ledger_entry_before_finalize(api):
    """PRD §3.10: "The program's derived `subsidy_consumed_cents` is exactly the
    signed sum of `amount_cents` across its entries".
    PRD §3.7: "For each finalized reservation a `SubsidyLedgerEntry` debit equal to
    the `final_subsidy_cents` with reason `RESERVATION_FINALIZED` is appended".

    Subsidy debits land only at trip completion, so a reserve-then-cancel before any
    completion leaves the program ledger empty and subsidy_consumed_cents at 0.

    Design: Difficulty/compensating_invariant/subsidy_budget_conservation_reserve_then_cancel_leaves_consumed
    """
    from test_helpers import validate_paginated
    ctx = setup_active_pool(api=api, hov_eligible=True, seed_rider_name="Rae",
                            seed_rider_wallet=50000)
    prog_id, drv_id, pool_id = ctx["program_id"], ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0, hov_lane_used=True)
    res = create_reservation(trip["id"], rider["id"], trip["version"], api=api,
                             seat_count=1, pay_now=True)
    get_success_data(api.cancel_reservation(res["id"], make_rider_headers(rider["id"])))
    entries, _meta = validate_paginated(api.list_program_ledger(prog_id, PA))
    assert len(entries) == 0
    assert get_success_data(api.get_employer_program(prog_id, PA))["subsidy_consumed_cents"] == 0
