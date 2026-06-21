"""Cost-share and subsidy arithmetic (PRD §2.7, §3.5, §3.7).

Covers the dual estimate/final cost-share divergence, the non-linear occupancy
tier factor, the per-layer subsidy rounding order, the trip total-cost per-mile
rounding, and the monthly-benefit subsidy cap.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    make_driver_headers, make_rider_headers, make_program_admin_headers,
    setup_active_pool, create_trip, create_reservation,
)

PA = make_program_admin_headers()


def _board_checkin_depart_complete(api, trip_id, drv_id, res_ids_to_checkin, hov_lane_used):
    get_success_data(api.open_boarding_trip(trip_id, make_driver_headers(drv_id)))
    for rid in res_ids_to_checkin:
        get_success_data(api.check_in_reservation(rid, make_driver_headers(drv_id)))
    get_success_data(api.depart_trip(trip_id, make_driver_headers(drv_id)))
    return get_success_data(api.complete_trip(
        trip_id, {"hov_lane_used": hov_lane_used}, make_driver_headers(drv_id)))


def test_cost_share_estimate_vs_final_diverge_when_co_rider_no_shows(api):
    """PRD §3.7: "For the estimate, N is forward-looking: the sum of `seat_count`
    over the trip's reservations that are `RESERVED` or `CHECKED_IN`, including the
    reservation being created."
    PRD §3.7: "For the final, N is the actuals: the sum of `seat_count` over only
    those reservations whose `reservation_status` is `COMPLETED` — riders who
    actually rode."

    R1 reserves first (forward N=1, factor 1.00) so estimate==3200; R2 reserves
    next (forward N=2, factor 1.00) so estimate==1600; R2 no-shows so only R1
    completes (final N=1) and final==3200, diverging from R2's estimate.

    Design: Difficulty/dual_variant_calc/cost_share_estimate_vs_final_diverges_on_no_show
    """
    ctx = setup_active_pool(api=api, base_cost_cents=2000, per_mile_cents=120,
                            seed_rider_name="Rae One", seed_rider_wallet=10000)
    prog_id, drv_id, pool_id = ctx["program_id"], ctx["driver_id"], ctx["pool_id"]
    r1 = ctx["seed"]
    # second rider
    r2 = get_success_data(api.create_member(
        {"employer_program_id": prog_id, "full_name": "Rae Two", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 10000}, PA))
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0, hov_lane_used=True)
    assert trip["total_cost_cents"] == 3200, "base 2000 + round(120*10.0)=3200"

    res1 = get_success_data(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": r1["id"],
         "expected_trip_version": trip["version"], "seat_count": 1, "pay_now": True},
        make_rider_headers(r1["id"])))
    assert res1["estimate_cost_share_cents"] == 3200

    trip_v1 = get_success_data(api.get_trip(trip["id"], make_driver_headers(drv_id)))["version"]
    res2 = get_success_data(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": r2["id"],
         "expected_trip_version": trip_v1, "seat_count": 1, "pay_now": True},
        make_rider_headers(r2["id"])))
    assert res2["estimate_cost_share_cents"] == 1600

    # R1 checks in; R2 stays RESERVED and is cascaded to NO_SHOW on depart.
    completed = _board_checkin_depart_complete(api, trip["id"], drv_id, [res1["id"]], True)
    assert completed["status"] == "COMPLETED"

    res1_final = get_success_data(api.get_reservation(res1["id"], make_driver_headers(drv_id)))
    res2_final = get_success_data(api.get_reservation(res2["id"], make_driver_headers(drv_id)))
    assert res1_final["final_cost_share_cents"] == 3200
    assert res2_final["reservation_status"] == "NO_SHOW"
    assert res1_final["final_cost_share_cents"] != res2_final["estimate_cost_share_cents"]


def test_cost_share_occupancy_tier_factor_is_nonlinear_at_four_seats(api):
    """PRD §3.7: "when N is at least 4 the factor is 0.80 (the full-vanpool
    discount), when N is exactly 3 the factor is 0.90, and when N is 2 or fewer the
    factor is 1.00."
    PRD §3.7: "The per-seat raw amount is the trip total multiplied by the tier
    factor, divided by N — kept as a real number, not yet rounded."

    On a 5000-cent trip the fourth reservation sees forward-looking N=4 (tier 0.80)
    so its estimate is 5000*0.80/4 == 1000.

    Design: Difficulty/combinatorial_formula/cost_share_tiered_occupancy_nonlinear_mode_a
    """
    ctx = setup_active_pool(api=api, base_cost_cents=3000, per_mile_cents=100,
                            seed_rider_name="R1", seed_rider_wallet=50000)
    prog_id, drv_id, pool_id = ctx["program_id"], ctx["driver_id"], ctx["pool_id"]
    riders = [ctx["seed"]]
    for nm in ("R2", "R3", "R4"):
        riders.append(get_success_data(api.create_member(
            {"employer_program_id": prog_id, "full_name": nm, "home_zone": "Z-N",
             "work_zone": "Z-DT", "wallet_balance_cents": 50000}, PA)))
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=20.0)
    assert trip["total_cost_cents"] == 5000, "base 3000 + round(100*20.0)=5000"

    last_est = None
    cur_ver = trip["version"]
    for rider in riders:
        res = get_success_data(api.create_reservation(
            {"trip_id": trip["id"], "rider_member_id": rider["id"],
             "expected_trip_version": cur_ver, "seat_count": 1},
            make_rider_headers(rider["id"])))
        last_est = res["estimate_cost_share_cents"]
        cur_ver = get_success_data(api.get_trip(trip["id"], make_driver_headers(drv_id)))["version"]
    assert last_est == 1000, f"4th reservation forward N=4 tier 0.80: 5000*0.8/4=1000, got {last_est}"


def test_subsidy_rounds_each_layer_before_summing(api):
    """PRD §3.7: "Each layer is rounded to cents on its own before the two are
    summed — the system never multiplies the cost-share by the sum of the two
    fractions and rounds once."
    PRD §3.7: "its `net_charge_cents` is set to the final cost-share minus the
    final subsidy floored at 0, that net charge is taken from the rider's wallet".

    cost-share 1505, hov_pct 0.50 -> round(752.5)=753; match_pct 0.33 ->
    round((1505-753)*0.33)=round(248.16)=248; raw subsidy 753+248==1001; net 504.

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
    assert final["final_subsidy_cents"] == 1001
    assert final["net_charge_cents"] == 504


def test_trip_total_cost_rounds_per_mile_product_before_adding_base(api):
    """PRD §3.5: "the pool's `per_mile_cents` multiplied by the trip's
    `distance_miles`, that single product rounded half-up to the nearest whole cent
    before the base is added."

    base 2000 + round_half_up(120 * 12.5 = 1500.0) == 3500.

    Design: Corner/calculations/trip_total_cost_per_mile_rounding
    """
    ctx = setup_active_pool(api=api, base_cost_cents=2000, per_mile_cents=120)
    trip = create_trip(ctx["pool_id"], ctx["driver_id"], api=api, distance_miles=12.5)
    assert trip["total_cost_cents"] == 3500


def test_subsidy_capped_by_remaining_monthly_benefit(api):
    """PRD §3.7: "the applied subsidy is the smallest of the raw subsidy, the
    member's remaining monthly benefit (the program's `monthly_benefit_cap_cents`
    minus the member's `month_benefit_used_cents`, floored at 0), and the cost-share
    itself."

    raw subsidy 1300 (hov 1000 + match 300 on cs 2000) is clipped to the 1200
    monthly cap; month_benefit_used_cents settles to 1200.

    Design: Corner/calculations/subsidy_capped_by_monthly_benefit_remaining
    """
    ctx = setup_active_pool(api=api, base_cost_cents=1000, per_mile_cents=100,
                            hov_eligible=True, seed_rider_name="Rae", seed_rider_wallet=50000,
                            program_overrides={"hov_discount_pct": 0.50,
                                               "employer_match_pct": 0.30,
                                               "monthly_benefit_cap_cents": 1200,
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
    assert final["final_cost_share_cents"] == 2000
    assert final["final_subsidy_cents"] == 1200
    member = get_success_data(api.get_member(rider["id"], PA))
    assert member["month_benefit_used_cents"] == 1200
