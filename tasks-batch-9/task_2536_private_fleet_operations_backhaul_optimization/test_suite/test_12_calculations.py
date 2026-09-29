"""Derived arithmetic: load walks, PM projection, award ranking, tiers and ceilings."""

from test_helpers import (
    MAINTENANCE,
    MANAGER,
    PLANNER,
    ApiErrorId,
    add_delivery_stop,
    add_other_stop,
    assign_resources,
    charge_penalty_events,
    close_out_trip,
    dispatch_trip,
    make_transport_manager_headers,
    new_backhaul_offer,
    new_domicile,
    new_driver,
    new_order,
    new_pay_plan,
    new_route_posting,
    new_store,
    new_telematics_event,
    new_trip,
    place_bid,
    plan_trip,
    read_driver,
    read_posting,
    read_store,
    read_tractor,
    read_trip,
    review_offer,
    run_stop,
    set_clock,
    setup_base_fleet,
    validate_error,
    validate_paginated,
    validate_success,
)

PUBLISHER = make_transport_manager_headers("user-tm-1")
AWARDER = make_transport_manager_headers("user-tm-2")


# ------------------------------------------------- the peak in-transit load ----


def _trip_that_handles_sixteen_hundred_cases():
    """One 600-case delivery, a 500-case pickup and a 500-case drop-off, in that order."""
    ctx = setup_base_fleet(
        "c1",
        store_overrides={"store_code": "S-4001"},
        trailer_overrides={"trailer_code": "TL-C1", "capacity_cases": 600},
    )
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-C1A",
                    planned_start_at="2026-08-20T06:00:00Z")
    first = add_delivery_stop(trip["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                              "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    second = add_other_stop(trip["id"], "VENDOR_PICKUP", 2, "2026-08-20T11:00:00Z",
                            "2026-08-20T11:45:00Z", 90, 70, segment_loaded=False, cases=500)
    third = add_other_stop(trip["id"], "DROP_OFF", 3, "2026-08-20T13:00:00Z",
                           "2026-08-20T13:20:00Z", 60, 55, segment_loaded=True, cases=500)
    return ctx, trip, (first, second, third)


def test_each_stop_rounds_its_own_service_minutes_before_the_trip_sums_them(api):
    """PRD §3.4: "For a `DELIVERY`, take the stop's `cases`, multiply by 60, divide by the
    store's `cases_per_hour_unload_rate`, round the result **up** to a whole minute, and
    then add a fixed fifteen minutes of setup and paperwork at the dock. For a
    `VENDOR_PICKUP` or a `THIRD_PARTY_PICKUP`, `service_minutes` is a flat forty-five
    minutes. For a `DROP_OFF` it is a flat twenty minutes, and for a `FUEL` stop a flat
    twenty-five minutes." And PRD §3.4: "`planned_break_minutes` is thirty minutes
    whenever `planned_drive_minutes` is strictly greater than eight hours of driving, and
    zero otherwise — the trigger sits at eight hours, so a trip with exactly eight hours
    of driving gets no mandatory break."

    Design: Corner/calculations/peak_case_load_is_the_running_maximum_not_the_cases_handled
    """
    _, trip, stops = _trip_that_handles_sixteen_hundred_cases()
    first, second, third = stops
    # 600 cases at 600 an hour is exactly sixty minutes of unload, plus the fixed fifteen.
    assert first["service_minutes"] == 75
    assert second["service_minutes"] == 45
    assert third["service_minutes"] == 20

    body = read_trip(trip["id"])
    assert body["stop_count"] == 3
    assert body["planned_service_minutes"] == 140
    assert body["planned_drive_minutes"] == 270
    assert body["planned_break_minutes"] == 0
    assert body["planned_duty_minutes"] == 410
    assert body["total_miles"] == 225
    assert body["loaded_miles"] == 155
    assert body["empty_miles"] == 70
    assert body["planned_end_at"].startswith("2026-08-20T13:20:00")
    # Only DELIVERY stops feed the case aggregate, so the 1000 cases moved at the
    # pickup and the drop-off are excluded.
    assert body["planned_delivery_cases"] == 600


def test_a_six_hundred_case_trailer_carries_sixteen_hundred_handled_cases(api):
    """PRD §3.4: "Then walk the stops in ascending sequence: at a `DELIVERY` subtract that
    stop's `cases` from the running load; at a `VENDOR_PICKUP` or `THIRD_PARTY_PICKUP` add
    that stop's `cases`; at a `DROP_OFF` subtract that stop's `cases`; at a `FUEL` stop
    leave the load unchanged. After each stop, if the running load is higher than the peak
    recorded so far, the peak becomes the running load. `peak_case_load` is the highest
    running load seen anywhere on that walk." And PRD §3.5: "Finally the **capacity and
    temperature** gates: the trip's `peak_case_load` must not exceed the assigned trailer's
    `capacity_cases`, where equality passes and any excess is
    `ERR_TRAILER_CAPACITY_EXCEEDED`; and if any `DELIVERY` stop's order has a
    `temperature_mode` of `REFRIGERATED`, the assigned trailer's `trailer_type` must be
    `REEFER`, else `ERR_TEMPERATURE_MODE_MISMATCH`."

    Design: Corner/calculations/peak_case_load_is_the_running_maximum_not_the_cases_handled
    """
    ctx, trip, _ = _trip_that_handles_sixteen_hundred_cases()
    # The walk runs 600 -> 0 -> 500 -> 0, so the departure load is the maximum.
    assert read_trip(trip["id"])["peak_case_load"] == 600

    assign_resources(trip["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    planned = plan_trip(trip["id"])
    assert planned["plan_status"] == "PLANNED"
    # Equality against capacity_cases 600 passes, although 1600 cases were handled.
    assert planned["peak_case_load"] == 600
    assert ctx["trailer"]["capacity_cases"] == 600


# --------------------------------------- the preventive-maintenance projection ----


def _tractor_fifty_miles_short_of_its_pm_interval():
    """A 60-mile PM interval with 50 miles already run: no hold now, PM_B after 100 miles."""
    ctx = setup_base_fleet(
        "c2",
        store_overrides={"store_code": "S-4002"},
        tractor_overrides={
            "unit_code": "TR-C2",
            "odometer_miles": 50000,
            "pm_interval_miles": 60,
            "pm_last_service_odometer": 49950,
        },
        trailer_overrides={"trailer_code": "TL-C2"},
    )
    assert ctx["tractor"]["miles_since_pm"] == 50
    assert ctx["tractor"]["pm_hold"] is False
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-C2A",
                    planned_start_at="2026-08-20T06:00:00Z")
    stop = add_delivery_stop(trip["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                             "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    assign_resources(trip["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    assert plan_trip(trip["id"])["total_miles"] == 100
    dispatch_trip(trip["id"])
    assert run_stop(stop["id"], ctx["driver"]["id"])["status"] == "COMPLETED"
    set_clock("2026-08-20T14:00:00Z")
    return ctx, trip


def _auto_generated_orders_of(api, tractor_id):
    listed, _meta = validate_paginated(
        api.list_work_orders(MAINTENANCE, {"tractor_id": tractor_id})
    )
    return [order for order in listed if order["auto_generated"] is True]


def test_the_close_out_odometer_drives_the_projection_to_pm_b(api):
    """PRD §3.7: "The tractor's `odometer_miles` rises by the trip's `total_miles`, and its
    `miles_since_pm` is then recomputed as the new `odometer_miles` less
    `pm_last_service_odometer` — the second link caused by the first." And PRD §3.7: "When
    `miles_since_pm` has reached or passed the tractor's `pm_interval_miles` — the boundary
    is inclusive, so a tractor landing exactly on its interval is due — a work order is
    created for that tractor with `asset_kind` of `TRACTOR`, `auto_generated` true, `status`
    of `SCHEDULED` and `deferral_count` at zero. Its `service_type` is `PM_B` when
    `miles_since_pm` has reached or passed twice the interval and `PM_A` otherwise."

    Design: Corner/calculations/pm_projection_selects_pm_b_at_twice_the_interval
    """
    ctx, trip = _tractor_fifty_miles_short_of_its_pm_interval()
    closed = close_out_trip(trip["id"], 120, 195)
    assert closed["plan_status"] == "COMPLETED"
    assert closed["delivered_cases"] == 600

    tractor = read_tractor(ctx["tractor"]["id"])
    assert tractor["odometer_miles"] == 50100
    assert tractor["miles_since_pm"] == 150

    orders = _auto_generated_orders_of(api, ctx["tractor"]["id"])
    assert len(orders) == 1
    order = orders[0]
    # 150 has reached twice the 60-mile interval, so the projection escalates past PM_A.
    assert order["service_type"] == "PM_B"
    assert order["asset_kind"] == "TRACTOR"
    assert order["tractor_id"] == ctx["tractor"]["id"]
    assert order["status"] == "SCHEDULED"
    assert order["deferral_count"] == 0


def test_the_projected_window_ignores_the_instant_the_trip_closed(api):
    """PRD §3.7: "Its window is pinned to clock-independent boundaries: `window_start_at` is
    the next UTC midnight after the logical clock's current instant, and `window_end_at` is
    eight hours after that start. The creation of that order then sets the tractor's
    `pm_hold` to true — a fourth link, caused by the third. At most one auto-generated PM
    order exists per tractor at a time: when `pm_hold` is already true the projection creates
    nothing." And PRD §3.7: "The tractor and the trailer both move `ASSIGNED → AVAILABLE`."

    Design: Corner/calculations/pm_projection_selects_pm_b_at_twice_the_interval
    """
    ctx, trip = _tractor_fifty_miles_short_of_its_pm_interval()
    close_out_trip(trip["id"], 120, 195)

    order = _auto_generated_orders_of(api, ctx["tractor"]["id"])[0]
    # The clock stood at 14:00 on the 20th; the window is the next midnight, not +8h.
    assert order["window_start_at"].startswith("2026-08-21T00:00:00")
    assert order["window_end_at"].startswith("2026-08-21T08:00:00")

    tractor = read_tractor(ctx["tractor"]["id"])
    assert tractor["pm_hold"] is True
    # Released by the trip and held by the PM at the same time.
    assert tractor["status"] == "AVAILABLE"


# ------------------------------------------------------- the award selection ----


def _board_with_three_bidders():
    """Two drivers tied on seniority plus the most senior driver, who decays after bidding."""
    set_clock()
    domicile = new_domicile(domicile_code="DOM-C3")
    plan = new_pay_plan(plan_code="MILE-C")
    driver_a = new_driver(domicile["id"], plan["id"], driver_code="D-C3A",
                          seniority_date="2016-03-01")
    driver_b = new_driver(domicile["id"], plan["id"], driver_code="D-C3B",
                          seniority_date="2016-03-01")
    driver_c = new_driver(domicile["id"], plan["id"], driver_code="D-C3C",
                          seniority_date="2014-01-01")
    b_event = new_telematics_event(driver_b["id"], "SEATBELT", 3, "2026-07-20T09:00:00Z")
    posting = new_route_posting(domicile["id"], PUBLISHER, route_code="RT-C3",
                               weekly_miles=2400, weekly_stops=20,
                               start_effective_date="2026-09-07",
                               bid_close_at="2026-08-10T00:00:00Z")
    bid_a = place_bid(driver_a["id"], posting["id"], read_posting(posting["id"])["version"])
    bid_b = place_bid(driver_b["id"], posting["id"], read_posting(posting["id"])["version"])
    bid_c = place_bid(driver_c["id"], posting["id"], read_posting(posting["id"])["version"])
    # Only now does the senior driver collect 21 points of exceptions.
    charge_penalty_events(driver_c["id"], [
        ("SEATBELT", 3, "2026-08-01T09:00:00Z"),
        ("SPEEDING", 3, "2026-08-01T10:00:00Z"),
    ])
    set_clock("2026-08-10T00:00:00Z")
    return {
        "posting": posting,
        "b_event": b_event,
        "drivers": (driver_a, driver_b, driver_c),
        "bids": (bid_a, bid_b, bid_c),
    }


def test_the_bid_snapshots_freeze_while_the_driver_row_moves_on(api):
    """PRD §3.9: "Each accepted bid records `seniority_date_snapshot` and
    `safety_score_snapshot`, copies of the driver's `seniority_date` and `safety_score` as
    they stood at bid time, kept for audit only." And PRD §3.9: "`safety_score` is one
    hundred less those open points, floored at zero so it never goes negative.
    `coaching_hold` is true exactly when `safety_score` is strictly below 70, which is to
    say when open points exceed thirty."

    Design: Corner/calculations/award_reads_live_driver_fields_and_ranks_by_seniority_then_safety
    """
    ctx = _board_with_three_bidders()
    bid_a, bid_b, bid_c = ctx["bids"]
    assert ctx["b_event"]["penalty_points"] == 12
    assert bid_a["safety_score_snapshot"] == 100
    assert bid_b["safety_score_snapshot"] == 88
    assert bid_c["safety_score_snapshot"] == 100
    assert bid_c["seniority_date_snapshot"] == "2014-01-01"

    live_c = read_driver(ctx["drivers"][2]["id"])
    # 12 for the seatbelt plus 9 for the speeding exception.
    assert live_c["open_penalty_points"] == 21
    assert live_c["safety_score"] == 79
    # Under the award floor of 80 but still clear of the coaching threshold.
    assert live_c["coaching_hold"] is False


def test_the_award_drops_the_decayed_senior_and_breaks_the_tie_on_safety(api):
    """PRD §3.9: "The candidate pool is every bid of this posting whose status is `SUBMITTED`
    and whose driver, read **live** at award time, is `ACTIVE`, has `coaching_hold` false,
    has a `safety_score` of 80 or above, and has a `domicile_id` equal to the posting's
    `domicile_id`. The live driver row governs: the `safety_score_snapshot` and
    `seniority_date_snapshot` stored on the bid are audit records and are never consulted by
    the selection, so a driver whose score has decayed since bidding is dropped and a driver
    whose score has recovered is admitted. Candidates are then ranked by `seniority_date`
    ascending, the earlier date being the more senior claim. Ties on seniority are broken by
    `safety_score` descending, and any remaining tie by the bid's own `created_at` ascending,
    first bid winning." And PRD §3.9: "The winning bid moves `SUBMITTED → AWARDED`, every
    other `SUBMITTED` bid moves to `PASSED_OVER`, the posting's `awarded_driver_id` is set to
    the winner's driver, the posting moves `OPEN → AWARDED`, its `bid_count` is set outright
    to zero, and its `version` advances."

    Design: Corner/calculations/award_reads_live_driver_fields_and_ranks_by_seniority_then_safety
    """
    ctx = _board_with_three_bidders()
    driver_a, _driver_b, driver_c = ctx["drivers"]
    bid_a, bid_b, bid_c = ctx["bids"]

    awarded = validate_success(api.award_route_posting(ctx["posting"]["id"], AWARDER))
    assert awarded["status"] == "AWARDED"
    # The earliest seniority_date belongs to the driver the live safety floor excludes.
    assert awarded["awarded_driver_id"] == driver_a["id"]
    assert awarded["awarded_driver_id"] != driver_c["id"]
    assert awarded["bid_count"] == 0

    def status_of(bid):
        return validate_success(api.get_route_bid(bid["id"], MANAGER))["status"]

    assert status_of(bid_a) == "AWARDED"
    assert status_of(bid_b) == "PASSED_OVER"
    assert status_of(bid_c) == "PASSED_OVER"


# ------------------------------------------------ the brokerage commission tier ----


def _two_offers_seven_cents_apart():
    """Identical costs; the revenue difference straddles the pre-commission tier key."""
    set_clock()
    store = new_store(store_code="S-4004")
    shape = {
        "cases": 500,
        "deadhead_miles": 40,
        "loaded_miles": 160,
        "temperature_mode": "DRY",
        "pickup_window_start": "2026-08-20T14:00:00Z",
        "pickup_window_end": "2026-08-20T20:00:00Z",
        "offer_expires_at": "2026-08-18T00:00:00Z",
    }
    high = new_backhaul_offer(store["id"], shipper_name="Tier High Foods",
                              revenue_cents=51875, **shape)
    low = new_backhaul_offer(store["id"], shipper_name="Tier Low Foods",
                             revenue_cents=51868, **shape)
    return high, low


def test_a_pre_commission_ratio_of_exactly_two_tenths_pays_the_six_percent_rate(api):
    """PRD §3.6: "A new offer's `status` is `PROPOSED`, its `review_round` is zero, its
    `margin_exception_approved` flag is false, its `created_by_user_id` records the sourcing
    planner's operator identifier, and all six of its computed margin fields sit at zero —
    they are not computed until the offer enters review." And PRD §3.6: "Step seven produces
    the **tier key**: `tier_margin_pct` is `gross_margin_cents` divided by `revenue_cents`,
    rounded half up to four decimal places. Step eight selects the commission rate from that
    tier key and from nothing else: when `tier_margin_pct` is at or above 20 percent the
    brokerage rate is 6 percent of revenue, and otherwise it is 3 percent of revenue. Step
    nine computes `commission_cents` as `revenue_cents` multiplied by the selected rate,
    rounded half up. Step ten sets `contribution_margin_cents` to `gross_margin_cents` less
    `commission_cents`. Step eleven reports `margin_pct` as `contribution_margin_cents`
    divided by `revenue_cents`, rounded half up to four decimal places."

    Design: Corner/calculations/commission_tier_flips_at_a_pre_commission_ratio_of_exactly_0_2000
    """
    high, _low = _two_offers_seven_cents_apart()
    assert high["status"] == "PROPOSED"
    assert high["review_round"] == 0
    assert high["margin_exception_approved"] is False
    for field in ("variable_cost_cents", "gross_margin_cents", "tier_margin_pct",
                  "commission_cents", "contribution_margin_cents", "margin_pct"):
        assert high[field] == 0

    priced = review_offer(high["id"])
    assert priced["status"] == "UNDER_REVIEW"
    # 200 incremental miles at 185 plus 500 cases at 9, and no reefer surcharge.
    assert priced["variable_cost_cents"] == 41500
    assert priced["gross_margin_cents"] == 10375
    assert priced["tier_margin_pct"] == 0.2
    # 51875 * 0.06 is 3112.5, which rounds half up.
    assert priced["commission_cents"] == 3113
    assert priced["contribution_margin_cents"] == 7262
    assert priced["margin_pct"] == 0.14


def test_seven_fewer_cents_of_revenue_keeps_fifteen_hundred_more_cents_of_margin(api):
    """PRD §3.6: "Step two, the linehaul variable cost is those incremental miles multiplied
    by a fleet running cost of 185 cents per mile, rounded half up to whole cents, and stored
    as the linehaul component. Step three, the handling cost is the offer's `cases`
    multiplied by 9 cents per case, rounded half up." And PRD §3.6: "`margin_pct` is the
    *reported* ratio and never re-enters the tier decision of step eight — keying the
    commission on the post-commission ratio changes the persisted
    `contribution_margin_cents` for any offer whose pre-commission ratio lands near the tier
    boundary, and is simply wrong."

    Design: Corner/calculations/commission_tier_flips_at_a_pre_commission_ratio_of_exactly_0_2000
    """
    high, low = _two_offers_seven_cents_apart()
    priced_high = review_offer(high["id"])
    priced_low = review_offer(low["id"])

    assert priced_low["variable_cost_cents"] == 41500
    assert priced_low["gross_margin_cents"] == 10368
    # 10368 / 51868 rounds to 0.1999, which sits one ten-thousandth under the tier.
    assert priced_low["tier_margin_pct"] == 0.1999
    assert priced_low["commission_cents"] == 1556
    assert priced_low["contribution_margin_cents"] == 8812
    assert priced_low["margin_pct"] == 0.1699

    # The cheaper offer is worth more, which only holds if the tier is keyed
    # on the pre-commission ratio.
    assert priced_low["contribution_margin_cents"] - priced_high["contribution_margin_cents"] == 1550


# ------------------------------------------------ the domicile balance index ----


def _domicile_targeting_seven_drivers():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-C5", region_code="WEST", tractor_capacity=12,
                            driver_headcount_target=7)
    plan = new_pay_plan(plan_code="MILE-C")
    drivers = [
        new_driver(domicile["id"], plan["id"], driver_code="D-C5" + letter,
                   seniority_date="2019-0%d-01" % index)
        for index, letter in enumerate("ABCDE", start=1)
    ]
    return domicile, drivers


def _read_domicile(api, domicile_id):
    return validate_success(api.get_domicile(domicile_id, MANAGER))


def test_five_of_seven_drivers_rounds_the_balance_index_up(api):
    """PRD §3.1: "A new domicile starts with `assigned_driver_count` at zero, `balance_index`
    at 0.0 and `accrued_pay_cents` at zero." And PRD §3.1: "The **balance index** is the
    domicile's staffing health: the count of that domicile's `ACTIVE` drivers divided by its
    `driver_headcount_target`, rounded half up to four decimal places. Terminated drivers
    leave the numerator immediately."

    Design: Corner/calculations/balance_index_rounds_to_four_decimals_half_up
    """
    domicile, drivers = _domicile_targeting_seven_drivers()
    assert domicile["assigned_driver_count"] == 0
    assert domicile["balance_index"] == 0.0
    assert len(drivers) == 5

    staffed = _read_domicile(api, domicile["id"])
    assert staffed["assigned_driver_count"] == 5
    # 5 / 7 is 0.714285..., which rounds up at the fourth decimal.
    assert staffed["balance_index"] == 0.7143


def test_four_of_seven_drivers_rounds_the_same_index_down(api):
    """PRD §3.3: "The domicile's `assigned_driver_count` falls by 1 and its `balance_index`
    is recomputed." And PRD §3.1: "Terminated drivers leave the numerator immediately."

    Design: Corner/calculations/balance_index_rounds_to_four_decimals_half_up
    """
    domicile, drivers = _domicile_targeting_seven_drivers()
    terminated = validate_success(
        api.terminate_driver(drivers[4]["id"], {"termination_reason": "VOLUNTARY"}, MANAGER)
    )
    assert terminated["status"] == "TERMINATED"

    reduced = _read_domicile(api, domicile["id"])
    assert reduced["assigned_driver_count"] == 4
    # 4 / 7 is 0.571428..., and the same half-up rule rounds this one down.
    assert reduced["balance_index"] == 0.5714


# ------------------------------------------------------- the short-counted stop ----


def _short_counted_stop(api):
    """A 600-case delivery checked out with only 300 cases handled."""
    ctx = setup_base_fleet(
        "c6",
        store_overrides={"store_code": "S-4006"},
        tractor_overrides={"unit_code": "TR-C6"},
        trailer_overrides={"trailer_code": "TL-C6"},
    )
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-C6A",
                    planned_start_at="2026-08-20T06:00:00Z")
    stop = add_delivery_stop(trip["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                             "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    assign_resources(trip["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    planned = plan_trip(trip["id"])
    ledger_before = read_store(ctx["store"]["id"])["open_scheduled_cases"]
    dispatch_trip(trip["id"])
    validate_success(api.arrive_at_stop(stop["id"], MANAGER))
    checked_out = validate_success(api.complete_stop(stop["id"], {"cases_handled": 300}, MANAGER))
    return ctx, trip, planned, ledger_before, checked_out


def test_a_short_count_rewrites_the_stop_and_re_derives_the_trip(api):
    """PRD §3.7: "It may also correct reality: when `cases_handled` is supplied, the stop's
    `cases` is overwritten with that value and the stop's `service_minutes` is recomputed
    from the new case count under the same per-stop rule of §3.4; when `cases_handled` is
    omitted, both are left alone. Because the case count feeds four trip aggregates,
    `planned_service_minutes`, `planned_duty_minutes`, `planned_delivery_cases` and
    `peak_case_load` are all re-derived on the parent trip."

    Design: Corner/calculations/short_count_completion_rewrites_the_trip_totals_but_not_the_store_ledger
    """
    _ctx, trip, planned, ledger_before, checked_out = _short_counted_stop(api)
    assert planned["planned_service_minutes"] == 75
    assert planned["planned_duty_minutes"] == 195
    assert planned["planned_delivery_cases"] == 600
    assert planned["peak_case_load"] == 600
    assert ledger_before == 600

    assert checked_out["status"] == "COMPLETED"
    assert checked_out["cases"] == 300
    # 300 cases at 600 an hour is thirty minutes of unload plus the fixed fifteen.
    assert checked_out["service_minutes"] == 45

    body = read_trip(trip["id"])
    assert body["planned_service_minutes"] == 45
    assert body["planned_duty_minutes"] == 165
    assert body["planned_delivery_cases"] == 300
    assert body["peak_case_load"] == 300


def test_the_store_ledger_moves_by_the_order_and_not_by_the_short_count(api):
    """PRD §3.7: "`delivered_cases` is set to the sum of `cases` over the trip's `DELIVERY`
    stops whose own status is `COMPLETED`." And PRD §3.7: "Each `COMPLETED` `DELIVERY`
    stop's replenishment order moves `SCHEDULED → DELIVERED`, and each order that reaches
    `DELIVERED` lowers its store's `open_scheduled_cases` by that order's `cases` while
    raising the store's `delivered_cases_total` by the same amount."

    Design: Corner/calculations/short_count_completion_rewrites_the_trip_totals_but_not_the_store_ledger
    """
    ctx, trip, _planned, _before, _checked_out = _short_counted_stop(api)
    closed = close_out_trip(trip["id"], 120, 165)
    assert closed["plan_status"] == "COMPLETED"
    assert closed["delivered_cases"] == 300

    order = validate_success(api.get_order(ctx["order"]["id"], PLANNER))
    assert order["status"] == "DELIVERED"
    # The short count never rewrites the demand it was working against.
    assert order["cases"] == 600

    store = read_store(ctx["store"]["id"])
    assert store["open_scheduled_cases"] == 0
    assert store["delivered_cases_total"] == 600


# ------------------------------------------------------ the daily drive ceiling ----


def _two_draft_trips_at_the_drive_ceiling():
    """One trip planning 661 drive minutes, one planning exactly 660, one driver at zero."""
    ctx = setup_base_fleet(
        "c7",
        store_overrides={"store_code": "S-4007"},
        tractor_overrides={"unit_code": "TR-C7"},
        trailer_overrides={"trailer_code": "TL-C7"},
        order_overrides={
            "requested_window_start": "2026-08-20T06:00:00Z",
            "requested_window_end": "2026-08-20T23:00:00Z",
        },
    )
    second_order = new_order(ctx["store"]["id"],
                             requested_window_start="2026-08-22T06:00:00Z",
                             requested_window_end="2026-08-22T23:00:00Z")
    bad = new_trip(ctx["domicile"]["id"], trip_code="TRIP-C7-BAD",
                   planned_start_at="2026-08-20T06:00:00Z")
    add_delivery_stop(bad["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                      "2026-08-20T17:01:00Z", "2026-08-20T18:16:00Z", 661, 520, 600)
    good = new_trip(ctx["domicile"]["id"], trip_code="TRIP-C7-OK",
                    planned_start_at="2026-08-22T06:00:00Z")
    add_delivery_stop(good["id"], ctx["store"]["id"], second_order["id"], 1,
                      "2026-08-22T17:00:00Z", "2026-08-22T18:15:00Z", 660, 519, 600)
    return ctx, bad, good


def _crew_payload(ctx):
    return {
        "driver_id": ctx["driver"]["id"],
        "tractor_id": ctx["tractor"]["id"],
        "trailer_id": ctx["trailer"]["id"],
    }


def test_one_minute_past_eleven_hours_of_driving_reports_the_drive_code(api):
    """PRD §3.5: "The three comparisons then run in a pinned order — drive, then duty, then
    weekly — so a trip that busts two of the three reports the first one in that order. A
    projected drive figure of more than eleven hours is `ERR_HOS_DRIVE_LIMIT`; a projected
    daily duty figure of more than fourteen hours is `ERR_HOS_DUTY_LIMIT`; a projected
    rolling-weekly figure of more than seventy hours is `ERR_HOS_WEEKLY_LIMIT`. All three
    comparisons are strict: a projection landing exactly on a ceiling is feasible. Note the
    asymmetry that `planned_duty_minutes` already contains `planned_break_minutes`, so the
    mandatory thirty-minute break consumes daily duty and rolling-weekly duty while never
    counting against the drive ceiling."

    Design: Corner/calculations/drive_limit_is_feasible_at_exactly_660_minutes
    """
    ctx, bad, _good = _two_draft_trips_at_the_drive_ceiling()
    assert ctx["driver"]["drive_minutes_used_today"] == 0
    assert ctx["driver"]["duty_minutes_used_today"] == 0

    body = read_trip(bad["id"])
    assert body["planned_drive_minutes"] == 661
    assert body["planned_break_minutes"] == 30
    # The projected duty figure of 766 stays far below the fourteen-hour ceiling.
    assert body["planned_duty_minutes"] == 766

    validate_error(
        api.assign_trip_resources(bad["id"], _crew_payload(ctx), MANAGER),
        ApiErrorId.ERR_HOS_DRIVE_LIMIT,
        422,
    )
    # The refused assignment claimed nothing, so the same assets remain free.
    assert read_tractor(ctx["tractor"]["id"])["status"] == "AVAILABLE"


def test_exactly_eleven_hours_of_driving_is_still_feasible(api):
    """PRD §3.5: "All three comparisons are strict: a projection landing exactly on a ceiling
    is feasible." And PRD §3.5: "On success the tractor and the trailer each move `AVAILABLE
    → ASSIGNED`, the trip records all three references, and the trip's `version` advances."

    Design: Corner/calculations/drive_limit_is_feasible_at_exactly_660_minutes
    """
    ctx, _bad, good = _two_draft_trips_at_the_drive_ceiling()
    body = read_trip(good["id"])
    assert body["planned_drive_minutes"] == 660
    assert body["planned_break_minutes"] == 30
    assert body["planned_duty_minutes"] == 765

    staffed = validate_success(api.assign_trip_resources(good["id"], _crew_payload(ctx), MANAGER))
    assert staffed["driver_id"] == ctx["driver"]["id"]
    assert staffed["tractor_id"] == ctx["tractor"]["id"]
    assert read_tractor(ctx["tractor"]["id"])["status"] == "ASSIGNED"
