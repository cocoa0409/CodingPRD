"""Thresholds probed from both sides, one unit apart, on minutes, ratios and scores."""

from test_helpers import (
    SAFETY,
    ApiErrorId,
    accept_offer,
    add_delivery_stop,
    add_other_stop,
    assign_resources,
    charge_penalty_events,
    link_offer,
    make_driver_headers,
    make_fleet_planner_headers,
    make_transport_manager_headers,
    new_backhaul_offer,
    new_domicile,
    new_driver,
    new_order,
    new_pay_plan,
    new_route_posting,
    new_store,
    new_tractor,
    new_trailer,
    new_trip,
    place_bid,
    read_driver,
    read_offer,
    read_posting,
    read_trip,
    review_offer,
    set_clock,
    setup_f1,
    validate_error,
)

MILE_A = {
    "plan_code": "MILE-A",
    "mileage_cents_per_mile": 78,
    "stop_cents_per_stop": 2200,
    "drop_hook_cents": 1500,
    "hourly_cents_per_minute": 42,
    "minimum_daily_cents": 24000,
    "backhaul_bonus_pct": 0.05,
}


def _eight_hour_driving_pair():
    """Two trips identical but for one drive minute on the final leg.

    TRIP-P drives 480 minutes and TRIP-Q drives 481. Two drivers and two rigs keep
    the pair from contending for equipment or for rest, and a 24-hour three-door
    store keeps dock geometry out of the way.
    """
    set_clock()
    store = new_store(store_code="S-1005", region_code="MOUNTAIN", dock_count=3,
                      cases_per_hour_unload_rate=600, dock_open_minute=0,
                      dock_close_minute=1439)
    domicile = new_domicile(domicile_code="DOM-SLC", region_code="MOUNTAIN",
                            tractor_capacity=30, driver_headcount_target=15,
                            fixed_ownership_cents_per_day=10000, overhead_cents_per_day=3000,
                            dedicated_rate_cents_per_mile=275,
                            dedicated_rate_cents_per_case=200)
    pay_plan = new_pay_plan(**MILE_A)
    first_driver = new_driver(domicile["id"], pay_plan["id"], driver_code="D-81",
                              seniority_date="2018-05-02")
    second_driver = new_driver(domicile["id"], pay_plan["id"], driver_code="D-82",
                               seniority_date="2020-06-15")
    first_tractor = new_tractor(domicile["id"], unit_code="TR-511", odometer_miles=30000,
                                pm_interval_miles=25000, pm_last_service_odometer=29000)
    second_tractor = new_tractor(domicile["id"], unit_code="TR-512", odometer_miles=31000,
                                 pm_interval_miles=25000, pm_last_service_odometer=30000)
    first_trailer = new_trailer(domicile["id"], trailer_code="VAN-910", capacity_cases=3200)
    second_trailer = new_trailer(domicile["id"], trailer_code="VAN-911", capacity_cases=3200)

    def one_day_trip(code, day, last_leg_drive, arrival, departure):
        order = new_order(store["id"], cases=600, weight_lbs=13000,
                          requested_window_start="2026-08-%sT00:00:00Z" % day,
                          requested_window_end="2026-08-%sT08:00:00Z" % day,
                          temperature_mode="DRY", priority=3)
        trip = new_trip(domicile["id"], trip_code=code,
                        planned_start_at="2026-08-%sT00:00:00Z" % day)
        delivery = add_delivery_stop(trip["id"], store["id"], order["id"], 1,
                                     "2026-08-%sT04:00:00Z" % day,
                                     "2026-08-%sT05:15:00Z" % day, 240, 240, 600)
        drop = add_other_stop(trip["id"], "DROP_OFF", 2, arrival, departure,
                              last_leg_drive, 200, True, cases=0)
        return trip, delivery, drop

    at_trigger, at_delivery, at_drop = one_day_trip(
        "TRIP-P", "07", 240, "2026-08-07T09:15:00Z", "2026-08-07T09:35:00Z"
    )
    over_trigger, _, _ = one_day_trip(
        "TRIP-Q", "08", 241, "2026-08-08T09:16:00Z", "2026-08-08T09:36:00Z"
    )
    return {
        "at_trigger_stops": (at_delivery, at_drop),
        "at_trigger": assign_resources(at_trigger["id"], first_driver["id"],
                                      first_tractor["id"], first_trailer["id"]),
        "over_trigger": assign_resources(over_trigger["id"], second_driver["id"],
                                        second_tractor["id"], second_trailer["id"]),
    }


def test_exactly_eight_hours_of_driving_earns_no_mandatory_break(api):
    """PRD §3.4: "`planned_break_minutes` is thirty minutes whenever
    `planned_drive_minutes` is strictly greater than eight hours of driving, and zero
    otherwise — the trigger sits at eight hours, so a trip with exactly eight hours of
    driving gets no mandatory break."

    Design: Difficulty/boundary_precision_check/break_minutes_appear_only_above_480_drive_minutes_not_at_480
    """
    ctx = _eight_hour_driving_pair()
    delivery, drop = ctx["at_trigger_stops"]
    assert delivery["service_minutes"] == 75
    assert drop["service_minutes"] == 20

    at_trigger = ctx["at_trigger"]
    assert at_trigger["planned_drive_minutes"] == 480
    assert at_trigger["planned_service_minutes"] == 95
    assert at_trigger["planned_break_minutes"] == 0
    assert at_trigger["planned_duty_minutes"] == 575


def test_one_drive_minute_past_the_trigger_costs_thirty_one_duty_minutes(api):
    """PRD §3.5: "Note the asymmetry that `planned_duty_minutes` already contains
    `planned_break_minutes`, so the mandatory thirty-minute break consumes daily duty and
    rolling-weekly duty while never counting against the drive ceiling."

    Design: Difficulty/boundary_precision_check/break_minutes_appear_only_above_480_drive_minutes_not_at_480
    """
    ctx = _eight_hour_driving_pair()
    over = ctx["over_trigger"]
    assert over["planned_drive_minutes"] == 481
    assert over["planned_service_minutes"] == 95
    assert over["planned_break_minutes"] == 30
    assert over["planned_duty_minutes"] == 606
    # One extra drive minute drags the whole thirty-minute break into duty.
    assert over["planned_duty_minutes"] - ctx["at_trigger"]["planned_duty_minutes"] == 31


# Both offers move 210 incremental miles of DRY freight for 400 cases, so they share a
# 42450-cent variable cost and a 1431-cent commission; only revenue differs.
THIN_OFFER = {
    "origin_kind": "VENDOR_PICKUP",
    "shipper_name": "Cascade Foods",
    "origin_region_code": "SOUTH",
    "cases": 400,
    "weight_lbs": 9000,
    "deadhead_miles": 42,
    "loaded_miles": 168,
    "temperature_mode": "DRY",
    "pickup_window_start": "2026-08-05T10:00:00Z",
    "pickup_window_end": "2026-08-05T16:00:00Z",
    "offer_expires_at": "2026-08-04T00:00:00Z",
}

SOURCING_PLANNER = "user-planner-1"
ACCEPTING_MANAGER = "user-tm-9"


def _thin_offer_on_a_planned_trip(revenue_cents):
    """A destination store, a planned trip to carry the offer, and the priced offer."""
    ctx = setup_f1(stage="planned")
    destination = new_store(store_code="S-1006", region_code="SOUTH", dock_count=2,
                            cases_per_hour_unload_rate=600, dock_open_minute=0,
                            dock_close_minute=1439)
    planner = make_fleet_planner_headers(SOURCING_PLANNER)
    created = new_backhaul_offer(destination["id"], headers=planner,
                                revenue_cents=revenue_cents, **THIN_OFFER)
    assert created["status"] == "PROPOSED"
    priced = review_offer(created["id"], planner)
    link_offer(ctx["trip"]["id"], created["id"], ctx["planned_trip"]["version"])
    ctx["offer"] = created
    ctx["priced"] = priced
    return ctx


def test_the_two_ratios_around_the_floor_are_seven_cents_of_revenue_apart(api):
    """PRD §3.6: "Step eleven reports `margin_pct` as `contribution_margin_cents` divided
    by `revenue_cents`, rounded half up to four decimal places."

    Design: Difficulty/boundary_precision_check/margin_floor_admits_exactly_0_0800_and_refuses_0_0799
    """
    set_clock()
    destination = new_store(store_code="S-1006", region_code="SOUTH", dock_count=2,
                            cases_per_hour_unload_rate=600, dock_open_minute=0,
                            dock_close_minute=1439)
    planner = make_fleet_planner_headers(SOURCING_PLANNER)
    at_floor = review_offer(
        new_backhaul_offer(destination["id"], headers=planner, revenue_cents=47697,
                           **THIN_OFFER)["id"],
        planner,
    )
    below_floor = review_offer(
        new_backhaul_offer(destination["id"], headers=planner, revenue_cents=47690,
                           **THIN_OFFER)["id"],
        planner,
    )
    assert at_floor["variable_cost_cents"] == 42450
    assert at_floor["gross_margin_cents"] == 5247
    assert at_floor["tier_margin_pct"] == 0.1100
    assert at_floor["commission_cents"] == 1431
    assert at_floor["contribution_margin_cents"] == 3816
    assert at_floor["margin_pct"] == 0.0800

    assert below_floor["variable_cost_cents"] == 42450
    assert below_floor["gross_margin_cents"] == 5240
    assert below_floor["tier_margin_pct"] == 0.1099
    assert below_floor["commission_cents"] == 1431
    assert below_floor["contribution_margin_cents"] == 3809
    assert below_floor["margin_pct"] == 0.0799


def test_a_ratio_landing_exactly_on_the_floor_is_accepted(api):
    """PRD §3.6: "The offer's `margin_pct` must be at or above the 8 percent
    contribution-margin floor; below the floor the acceptance is refused with
    `ERR_MARGIN_BELOW_FLOOR` unless the request carries `margin_exception_approved` as
    true."

    Design: Difficulty/boundary_precision_check/margin_floor_admits_exactly_0_0800_and_refuses_0_0799
    """
    ctx = _thin_offer_on_a_planned_trip(47697)
    assert ctx["priced"]["margin_pct"] == 0.0800
    accepted = accept_offer(ctx["offer"]["id"], make_transport_manager_headers(ACCEPTING_MANAGER))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["margin_exception_approved"] is False
    assert read_trip(ctx["trip"]["id"])["backhaul_credit_cents"] == 3816


def test_one_ten_thousandth_below_the_floor_is_refused_until_an_exception_is_claimed(api):
    """PRD §3.6: "And when a margin exception *is* claimed, the acting `X-User-ID` must
    differ from the offer's `created_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` —
    one operator may not both source a thin load and waive the floor on it."

    Design: Difficulty/boundary_precision_check/margin_floor_admits_exactly_0_0800_and_refuses_0_0799
    """
    ctx = _thin_offer_on_a_planned_trip(47690)
    assert ctx["priced"]["margin_pct"] == 0.0799
    manager = make_transport_manager_headers(ACCEPTING_MANAGER)
    validate_error(
        api.accept_offer(ctx["offer"]["id"], manager, {}),
        ApiErrorId.ERR_MARGIN_BELOW_FLOOR,
        422,
    )
    untouched = read_offer(ctx["offer"]["id"])
    assert untouched["status"] == "UNDER_REVIEW"
    assert untouched["margin_exception_approved"] is False

    waived = accept_offer(ctx["offer"]["id"], manager, margin_exception_approved=True)
    assert waived["status"] == "ACCEPTED"
    assert waived["margin_exception_approved"] is True
    assert read_trip(ctx["trip"]["id"])["backhaul_credit_cents"] == 3809


def _two_scores_around_the_bid_floor():
    """One driver on exactly 80 points of standing and one on 79, plus an open board."""
    set_clock()
    domicile = new_domicile(domicile_code="DOM-DEN", region_code="MOUNTAIN",
                            tractor_capacity=28, driver_headcount_target=14,
                            fixed_ownership_cents_per_day=10500, overhead_cents_per_day=3200,
                            dedicated_rate_cents_per_mile=278,
                            dedicated_rate_cents_per_case=202)
    pay_plan = new_pay_plan(**MILE_A)
    eligible = new_driver(domicile["id"], pay_plan["id"], driver_code="D-91",
                          seniority_date="2017-04-01")
    ineligible = new_driver(domicile["id"], pay_plan["id"], driver_code="D-92",
                            seniority_date="2016-04-01")
    assert eligible["safety_score"] == 100
    eligible_events = charge_penalty_events(
        eligible["id"],
        [
            ("SEATBELT", 3, "2026-07-20T12:00:00Z"),
            ("FOLLOWING_DISTANCE", 2, "2026-07-21T12:00:00Z"),
            ("HARD_BRAKE", 2, "2026-07-22T12:00:00Z"),
        ],
    )
    ineligible_events = charge_penalty_events(
        ineligible["id"],
        [
            ("SEATBELT", 3, "2026-07-20T12:00:00Z"),
            ("SPEEDING", 3, "2026-07-21T12:00:00Z"),
        ],
    )
    posting = new_route_posting(
        domicile["id"], headers=make_transport_manager_headers("user-tm-1"),
        route_code="RT-900", weekly_miles=2400, weekly_stops=40,
        start_effective_date="2026-09-01", bid_close_at="2026-08-20T00:00:00Z",
    )
    assert posting["bid_count"] == 0
    return {
        "eligible": eligible,
        "ineligible": ineligible,
        "eligible_events": eligible_events,
        "ineligible_events": ineligible_events,
        "posting": posting,
    }


def test_a_safety_score_of_exactly_eighty_may_still_bid(api):
    """PRD §2.7: "A driver under a coaching hold, or whose safety score sits below the
    bidding threshold of 80, may neither be assigned to a trip nor place a bid; and a
    driver's domicile must match the trip's domicile unless the cross-domicile borrow gate
    permits the loan."

    Design: Difficulty/boundary_precision_check/safety_score_of_exactly_80_may_bid_while_79_is_refused
    """
    ctx = _two_scores_around_the_bid_floor()
    points = [event["penalty_points"] for event in ctx["eligible_events"]]
    assert points == [12, 4, 4]
    standing = read_driver(ctx["eligible"]["id"], SAFETY)
    assert standing["open_penalty_points"] == 20
    assert standing["safety_score"] == 80
    assert standing["coaching_hold"] is False

    bid = place_bid(ctx["eligible"]["id"], ctx["posting"]["id"], ctx["posting"]["version"])
    assert bid["status"] == "SUBMITTED"
    assert bid["safety_score_snapshot"] == 80
    assert read_posting(ctx["posting"]["id"])["bid_count"] == 1


def test_a_safety_score_of_seventy_nine_is_refused_without_touching_the_board(api):
    """PRD §3.9: "a driver whose `safety_score` is below the award threshold is
    `ERR_DRIVER_SAFETY_INELIGIBLE`, and a driver domiciled elsewhere is
    `ERR_DOMICILE_MISMATCH`."

    Design: Difficulty/boundary_precision_check/safety_score_of_exactly_80_may_bid_while_79_is_refused
    """
    ctx = _two_scores_around_the_bid_floor()
    assert ctx["ineligible_events"][1]["penalty_points"] == 9
    standing = read_driver(ctx["ineligible"]["id"], SAFETY)
    assert standing["open_penalty_points"] == 21
    assert standing["safety_score"] == 79
    # The hold threshold is a separate rule at 70, so only the bid floor can be blocking.
    assert standing["coaching_hold"] is False

    place_bid(ctx["eligible"]["id"], ctx["posting"]["id"], ctx["posting"]["version"])
    before = read_posting(ctx["posting"]["id"])
    validate_error(
        api.create_route_bid(
            {
                "route_posting_id": ctx["posting"]["id"],
                "expected_posting_version": before["version"],
            },
            make_driver_headers(ctx["ineligible"]["id"]),
        ),
        ApiErrorId.ERR_DRIVER_SAFETY_INELIGIBLE,
        422,
    )
    after = read_posting(ctx["posting"]["id"])
    assert after["bid_count"] == 1
    assert after["version"] == before["version"]
