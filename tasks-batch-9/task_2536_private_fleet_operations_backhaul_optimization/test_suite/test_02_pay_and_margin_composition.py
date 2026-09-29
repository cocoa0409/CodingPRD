"""Component-by-component composition inside the pay engine and the margin engine."""

from test_helpers import (
    F1_STORE,
    PAYROLL,
    PLANNER,
    add_delivery_stop,
    api_client,
    assign_resources,
    get_success_data,
    make_fleet_planner_headers,
    make_transport_manager_headers,
    new_backhaul_offer,
    new_domicile,
    new_driver,
    new_order,
    new_pay_plan,
    new_store,
    new_tractor,
    new_trailer,
    new_trip,
    plan_trip,
    review_offer,
    set_clock,
    setup_f1,
    validate_paginated,
)

# The offer that rides along with the canonical trip: 210 incremental miles of DRY
# freight for 54000 cents of revenue.
B1 = {
    "origin_kind": "VENDOR_PICKUP",
    "shipper_name": "ACME MILLS",
    "origin_region_code": "MIDWEST",
    "revenue_cents": 54000,
    "cases": 400,
    "weight_lbs": 9000,
    "deadhead_miles": 42,
    "loaded_miles": 168,
    "temperature_mode": "DRY",
    "pickup_window_start": "2026-08-03T11:30:00Z",
    "pickup_window_end": "2026-08-03T13:00:00Z",
    "offer_expires_at": "2026-08-06T00:00:00Z",
}

# MILE-A with the daily guarantee raised until the floor actually binds.
MILE_G = {"plan_code": "MILE-G", "minimum_daily_cents": 30000}


def _bonus_trip():
    """The canonical trip, closed out on 340/560 minutes with B1 accepted on it."""
    return setup_f1(
        stage="completed",
        pay_plan_overrides=MILE_G,
        actual_drive_minutes=340,
        actual_duty_minutes=560,
        offer=B1,
        offer_headers=make_fleet_planner_headers("user-fp-1"),
        accept_headers=make_transport_manager_headers("user-tm-1"),
    )


def _statement(trip_id):
    rows, meta = validate_paginated(api_client.list_pay_statements(PAYROLL, {"trip_id": trip_id}))
    assert meta["total_count"] == 1
    return rows[0]


def test_backhaul_bonus_is_taken_on_mileage_plus_activity_and_never_on_detention(api):
    """PRD §3.8: "In that case the bonus is the sum of the mileage component and the
    activity component, multiplied by the plan's `backhaul_bonus_pct`, rounded half up;
    otherwise the bonus is zero."

    Design: Difficulty/combinatorial_formula/trip_pay_mode_a_nested_bonus_detention_and_guarantee_floor_compose
    """
    ctx = _bonus_trip()
    statement = _statement(ctx["trip"]["id"])
    assert statement["mileage_cents"] == 21294
    assert statement["activity_cents"] == 5900
    assert statement["hourly_cents"] == 1050
    assert statement["bonus_cents"] == 1360
    # 1412 would be the bonus taken on the full 28244-cent subtotal.
    assert statement["bonus_cents"] != 1412


def test_guarantee_makeup_tops_up_the_already_summed_and_rounded_subtotal(api):
    """PRD §3.8: "The **guarantee makeup** is the plan's `minimum_daily_cents` less that
    subtotal when the plan floor is higher, and zero when the subtotal already clears
    the floor."

    Design: Difficulty/combinatorial_formula/trip_pay_mode_a_nested_bonus_detention_and_guarantee_floor_compose
    """
    ctx = _bonus_trip()
    statement = _statement(ctx["trip"]["id"])
    components = (
        statement["mileage_cents"]
        + statement["activity_cents"]
        + statement["hourly_cents"]
        + statement["bonus_cents"]
    )
    assert components == 29604
    assert statement["guarantee_makeup_cents"] == 30000 - components
    assert statement["guarantee_makeup_cents"] == 396
    assert statement["gross_cents"] == 30000
    assert components + statement["guarantee_makeup_cents"] == statement["gross_cents"]


def test_detention_grace_and_the_accepted_credit_ride_on_the_same_close_out(api):
    """PRD §3.8: "The trip's `backhaul_credit_cents` is set to the linked offer's
    `contribution_margin_cents` when that offer's status is `ACCEPTED`, and to zero
    otherwise."

    Design: Difficulty/combinatorial_formula/trip_pay_mode_a_nested_bonus_detention_and_guarantee_floor_compose
    """
    ctx = _bonus_trip()
    assert ctx["reviewed_offer"]["contribution_margin_cents"] == 8310
    assert ctx["offer"]["status"] == "ACCEPTED"
    assert ctx["trip"]["backhaul_credit_cents"] == 8310
    assert ctx["trip"]["driver_pay_cents"] == 30000
    # The accrual ran while no offer was linked: 27194 lifted by a 2806-cent makeup.
    assert ctx["planned_trip"]["planned_pay_cents"] == 30000
    assert ctx["planned_trip"]["backhaul_credit_cents"] == 0


def _two_door_trip():
    """Two deliveries at a 700-case/hour store: 900 cases then 500 cases.

    900 cases is 77.142857 exact unload minutes and 500 cases is 42.857143, so the
    per-stop ceiling and the aggregate ceiling disagree by exactly one minute.
    """
    set_clock()
    store = new_store(
        store_code="S-1003",
        region_code="MIDWEST",
        dock_count=2,
        cases_per_hour_unload_rate=700,
        dock_open_minute=0,
        dock_close_minute=1439,
    )
    domicile = new_domicile(
        domicile_code="DOM-STL",
        region_code="MIDWEST",
        tractor_capacity=30,
        driver_headcount_target=15,
        fixed_ownership_cents_per_day=9000,
        overhead_cents_per_day=3000,
        dedicated_rate_cents_per_mile=300,
        dedicated_rate_cents_per_case=220,
    )
    pay_plan = new_pay_plan(
        plan_code="MILE-B",
        mileage_cents_per_mile=80,
        stop_cents_per_stop=2000,
        drop_hook_cents=1400,
        hourly_cents_per_minute=40,
        minimum_daily_cents=20000,
        backhaul_bonus_pct=0.04,
    )
    driver = new_driver(domicile["id"], pay_plan["id"], driver_code="D-31",
                        seniority_date="2020-07-15")
    tractor = new_tractor(domicile["id"], unit_code="TR-503", odometer_miles=40000,
                          pm_interval_miles=25000, pm_last_service_odometer=39000)
    trailer = new_trailer(domicile["id"], trailer_code="VAN-903", trailer_type="DRY_VAN",
                          capacity_cases=1500, inspection_due_at="2026-12-01T00:00:00Z")
    order_a = new_order(store["id"], cases=900, weight_lbs=20000,
                        requested_window_start="2026-08-04T07:00:00Z",
                        requested_window_end="2026-08-04T11:00:00Z",
                        temperature_mode="DRY", priority=3)
    order_b = new_order(store["id"], cases=500, weight_lbs=11000,
                        requested_window_start="2026-08-04T10:30:00Z",
                        requested_window_end="2026-08-04T13:00:00Z",
                        temperature_mode="DRY", priority=3)
    trip = new_trip(domicile["id"], trip_code="TRIP-R1",
                    planned_start_at="2026-08-04T06:00:00Z")
    stop_a = add_delivery_stop(trip["id"], store["id"], order_a["id"], 1,
                               "2026-08-04T08:00:00Z", "2026-08-04T10:00:00Z", 105, 100, 900)
    # A second door at the same store, so no drive and no miles between them.
    stop_b = add_delivery_stop(trip["id"], store["id"], order_b["id"], 2,
                               "2026-08-04T11:00:00Z", "2026-08-04T12:00:00Z", 0, 0, 500)
    assign_resources(trip["id"], driver["id"], tractor["id"], trailer["id"])
    return {
        "store": store,
        "trip": trip,
        "stops": [stop_a, stop_b],
        "planned": plan_trip(trip["id"]),
    }


def test_each_stop_rounds_its_unload_minutes_up_before_the_trip_sums_them(api):
    """PRD §3.4: "The rounding order here is part of the contract and is stated again
    because it is easy to get wrong: the rounding up happens *at each stop*, and the
    whole-minute results are then added together."

    Design: Difficulty/combinatorial_formula/trip_plan_totals_mode_b_per_stop_ceiling_before_aggregation
    """
    ctx = _two_door_trip()
    first = get_success_data(api.get_trip_stop(ctx["stops"][0]["id"], PLANNER))
    second = get_success_data(api.get_trip_stop(ctx["stops"][1]["id"], PLANNER))
    assert first["service_minutes"] == 93
    assert second["service_minutes"] == 58
    assert ctx["planned"]["planned_service_minutes"] == 151
    assert first["service_minutes"] + second["service_minutes"] == 151
    # 150 is the aggregate-then-ceiling reading.
    assert ctx["planned"]["planned_service_minutes"] != 150


def test_the_extra_service_minute_carries_through_into_planned_duty(api):
    """PRD §3.4: "`planned_duty_minutes` is the sum of planned drive minutes, planned
    service minutes and planned break minutes."

    Design: Difficulty/combinatorial_formula/trip_plan_totals_mode_b_per_stop_ceiling_before_aggregation
    """
    ctx = _two_door_trip()
    planned = ctx["planned"]
    assert planned["planned_drive_minutes"] == 105
    assert planned["planned_break_minutes"] == 0
    assert planned["planned_duty_minutes"] == 256
    assert planned["planned_duty_minutes"] != 255
    assert (
        planned["planned_drive_minutes"]
        + planned["planned_service_minutes"]
        + planned["planned_break_minutes"]
        == planned["planned_duty_minutes"]
    )
    assert planned["peak_case_load"] == 1400
    assert planned["total_miles"] == 100
    assert planned["planned_delivery_cases"] == 1400


B2 = {
    "origin_kind": "THIRD_PARTY",
    "shipper_name": "NORTHSTAR COLD",
    "origin_region_code": "MIDWEST",
    "revenue_cents": 60000,
    "cases": 300,
    "weight_lbs": 8000,
    "deadhead_miles": 30,
    "loaded_miles": 200,
    "temperature_mode": "REFRIGERATED",
    "pickup_window_start": "2026-08-04T09:00:00Z",
    "pickup_window_end": "2026-08-04T15:00:00Z",
    "offer_expires_at": "2026-08-06T00:00:00Z",
}


def _offer_store():
    """A destination store, which is all the margin calculation ever needs."""
    set_clock()
    return new_store(**F1_STORE)


def test_a_high_tier_offer_pays_six_percent_keyed_on_the_pre_commission_ratio(api):
    """PRD §3.6: "Step eight selects the commission rate from that tier key and from
    nothing else: when `tier_margin_pct` is at or above 20 percent the brokerage rate is
    6 percent of revenue, and otherwise it is 3 percent of revenue."

    Design: Difficulty/combinatorial_formula/backhaul_margin_mode_c_pre_commission_tier_breaks_the_circular_dependency
    """
    store = _offer_store()
    created = new_backhaul_offer(store["id"], **B1)
    assert created["status"] == "PROPOSED"
    assert created["review_round"] == 0
    for field in (
        "variable_cost_cents",
        "gross_margin_cents",
        "tier_margin_pct",
        "commission_cents",
        "contribution_margin_cents",
        "margin_pct",
    ):
        assert created[field] == 0

    priced = review_offer(created["id"])
    assert priced["variable_cost_cents"] == 42450
    assert priced["gross_margin_cents"] == 11550
    assert priced["tier_margin_pct"] == 0.2139
    assert priced["commission_cents"] == 3240
    assert priced["contribution_margin_cents"] == 8310
    assert priced["margin_pct"] == 0.1539
    # The circular reading keys the 3 percent rate on the reported 0.1539 ratio.
    assert priced["commission_cents"] != 1620
    assert priced["contribution_margin_cents"] != 9930
    assert priced["margin_pct"] != 0.1839


def test_a_refrigerated_low_tier_offer_pays_three_percent_over_a_reefer_surcharge(api):
    """PRD §3.6: "Step four, the reefer surcharge applies only when `temperature_mode` is
    `REFRIGERATED`, and it is charged on the loaded miles alone — `loaded_miles`
    multiplied by 22 cents per mile, rounded half up — while a `DRY` offer carries no
    surcharge at all."

    Design: Difficulty/combinatorial_formula/backhaul_margin_mode_c_pre_commission_tier_breaks_the_circular_dependency
    """
    store = _offer_store()
    created = new_backhaul_offer(store["id"], **B2)
    assert created["status"] == "PROPOSED"
    assert created["review_round"] == 0

    priced = review_offer(created["id"])
    # 230 incremental miles at 185, 300 cases at 9, and 200 loaded miles at 22.
    assert priced["variable_cost_cents"] == 49650
    assert priced["gross_margin_cents"] == 10350
    assert priced["tier_margin_pct"] == 0.1725
    assert priced["commission_cents"] == 1800
    assert priced["contribution_margin_cents"] == 8550
    assert priced["margin_pct"] == 0.1425


def test_the_reported_ratio_never_feeds_back_into_the_commission_tier(api):
    """PRD §3.6: "`margin_pct` is the *reported* ratio and never re-enters the tier
    decision of step eight — keying the commission on the post-commission ratio changes
    the persisted `contribution_margin_cents` for any offer whose pre-commission ratio
    lands near the tier boundary, and is simply wrong."

    Design: Difficulty/combinatorial_formula/backhaul_margin_mode_c_pre_commission_tier_breaks_the_circular_dependency
    """
    store = _offer_store()
    high = review_offer(new_backhaul_offer(store["id"], **B1)["id"])
    low = review_offer(new_backhaul_offer(store["id"], **B2)["id"])

    # Both offers report a margin_pct under 0.20, yet only one paid the low rate.
    assert high["margin_pct"] < 0.20
    assert low["margin_pct"] < 0.20
    assert high["tier_margin_pct"] >= 0.20
    assert low["tier_margin_pct"] < 0.20
    assert high["commission_cents"] == 3240
    assert low["commission_cents"] == 1800
    for priced in (high, low):
        assert (
            priced["gross_margin_cents"] - priced["commission_cents"]
            == priced["contribution_margin_cents"]
        )
