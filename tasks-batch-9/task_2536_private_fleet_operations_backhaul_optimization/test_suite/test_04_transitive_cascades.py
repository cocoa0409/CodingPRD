"""Cascades whose later links are caused only by the link before them."""

from datetime import datetime

from test_helpers import (
    MAINTENANCE,
    MANAGER,
    PLANNER,
    SAFETY,
    ApiErrorId,
    add_delivery_stop,
    api_client,
    close_out_trip,
    get_success_data,
    make_transport_manager_headers,
    new_domicile,
    new_driver,
    new_order,
    new_pay_plan,
    new_route_posting,
    new_telematics_event,
    new_trip,
    place_bid,
    read_driver,
    read_posting,
    read_store,
    read_tractor,
    read_trip,
    set_clock,
    setup_f1,
    validate_error,
    validate_paginated,
)


def _instant(value: str) -> datetime:
    """Parse an API instant so two spellings of the same moment compare equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _pm_cascade():
    """TRIP-1 walked to its last stop, with a second trip waiting on the tractor.

    TR-501 sits 24800 miles into a 25000-mile interval, so the trip's 273 miles
    push it over.
    """
    ctx = setup_f1(stage="stops_done")
    ctx["second_driver"] = new_driver(
        ctx["domicile"]["id"], ctx["pay_plan"]["id"],
        driver_code="D-88", seniority_date="2021-02-01",
    )
    ctx["second_order"] = new_order(
        ctx["store"]["id"], cases=300, weight_lbs=7000,
        requested_window_start="2026-08-08T08:00:00Z",
        requested_window_end="2026-08-08T12:00:00Z",
        temperature_mode="DRY", priority=3,
    )
    ctx["second_trip"] = new_trip(
        ctx["domicile"]["id"], trip_code="TRIP-2", planned_start_at="2026-08-08T07:00:00Z"
    )
    add_delivery_stop(
        ctx["second_trip"]["id"], ctx["store"]["id"], ctx["second_order"]["id"], 1,
        "2026-08-08T09:00:00Z", "2026-08-08T10:00:00Z", 120, 120, 300,
    )
    # Pin the projected shop window: the next UTC midnight after this instant.
    set_clock("2026-08-03T16:00:00Z")
    close_out_trip(ctx["trip"]["id"], 340, 560)
    return ctx


def test_close_out_advances_the_odometer_and_then_recomputes_miles_since_pm(api):
    """PRD §3.7: "The tractor's `odometer_miles` rises by the trip's `total_miles`, and its
    `miles_since_pm` is then recomputed as the new `odometer_miles` less
    `pm_last_service_odometer` — the second link caused by the first."

    Design: Difficulty/transitive_cascade/trip_completion_cascades_odometer_to_auto_pm_order_to_pm_hold_to_refused_assignment
    """
    ctx = _pm_cascade()
    assert ctx["tractor"]["miles_since_pm"] == 24800
    assert ctx["tractor"]["pm_hold"] is False

    tractor = read_tractor(ctx["tractor"]["id"])
    assert tractor["odometer_miles"] == 125073
    assert tractor["miles_since_pm"] == 25073
    assert tractor["odometer_miles"] - tractor["pm_last_service_odometer"] == 25073


def test_crossing_the_interval_projects_exactly_one_auto_generated_pm_a_order(api):
    """PRD §3.7: "Its `service_type` is `PM_B` when `miles_since_pm` has reached or passed
    twice the interval and `PM_A` otherwise."

    Design: Difficulty/transitive_cascade/trip_completion_cascades_odometer_to_auto_pm_order_to_pm_hold_to_refused_assignment
    """
    ctx = _pm_cascade()
    orders, meta = validate_paginated(
        api.list_work_orders(MAINTENANCE, {"tractor_id": ctx["tractor"]["id"]})
    )
    assert meta["total_count"] == 1
    order = orders[0]
    # 25073 is one interval in, not two, so PM_B is wrong here.
    assert order["service_type"] == "PM_A"
    assert order["auto_generated"] is True
    assert order["status"] == "SCHEDULED"
    assert order["deferral_count"] == 0
    assert order["asset_kind"] == "TRACTOR"
    assert order["tractor_id"] == ctx["tractor"]["id"]


def test_the_projected_shop_window_starts_at_the_next_utc_midnight(api):
    """PRD §3.7: "Its window is pinned to clock-independent boundaries: `window_start_at`
    is the next UTC midnight after the logical clock's current instant, and
    `window_end_at` is eight hours after that start."

    Design: Difficulty/transitive_cascade/trip_completion_cascades_odometer_to_auto_pm_order_to_pm_hold_to_refused_assignment
    """
    ctx = _pm_cascade()
    orders, _ = validate_paginated(
        api.list_work_orders(MAINTENANCE, {"tractor_id": ctx["tractor"]["id"]})
    )
    order = orders[0]
    assert _instant(order["window_start_at"]) == _instant("2026-08-04T00:00:00Z")
    assert _instant(order["window_end_at"]) == _instant("2026-08-04T08:00:00Z")


def test_the_projected_order_holds_a_tractor_the_completion_had_just_released(api):
    """PRD §3.7: "The creation of that order then sets the tractor's `pm_hold` to true — a
    fourth link, caused by the third."

    Design: Difficulty/transitive_cascade/trip_completion_cascades_odometer_to_auto_pm_order_to_pm_hold_to_refused_assignment
    """
    ctx = _pm_cascade()
    tractor = read_tractor(ctx["tractor"]["id"])
    assert tractor["pm_hold"] is True
    # The close-out released the equipment; only the maintenance flag blocks it now.
    assert tractor["status"] == "AVAILABLE"


def test_the_pm_hold_then_refuses_the_next_assignment_of_that_tractor(api):
    """PRD §3.5: "a tractor or trailer that is not `AVAILABLE` is refused with
    `ERR_ASSET_NOT_AVAILABLE`, and a tractor whose `pm_hold` is true is refused with
    `ERR_TRACTOR_PM_HOLD`."

    Design: Difficulty/transitive_cascade/trip_completion_cascades_odometer_to_auto_pm_order_to_pm_hold_to_refused_assignment
    """
    ctx = _pm_cascade()
    validate_error(
        api.assign_trip_resources(
            ctx["second_trip"]["id"],
            {
                "driver_id": ctx["second_driver"]["id"],
                "tractor_id": ctx["tractor"]["id"],
                "trailer_id": ctx["trailer"]["id"],
            },
            MANAGER,
        ),
        ApiErrorId.ERR_TRACTOR_PM_HOLD,
        409,
    )
    refused = read_trip(ctx["second_trip"]["id"])
    assert refused["tractor_id"] is None
    assert refused["plan_status"] == "DRAFT"


def _coaching_hold_cascade(events: int = 3):
    """A planned trip and an open bid held by a driver taking seatbelt exceptions.

    Each severity-3 seatbelt event is worth twelve points, so the third one is what
    pushes open points past thirty.
    """
    ctx = setup_f1(stage="planned")
    posting = new_route_posting(
        ctx["domicile"]["id"], headers=make_transport_manager_headers("user-tm-1"),
        route_code="RT-100", weekly_miles=2200, weekly_stops=18,
        start_effective_date="2026-09-01", bid_close_at="2026-08-10T00:00:00Z",
    )
    ctx["posting"] = posting
    ctx["bid"] = place_bid(ctx["driver"]["id"], posting["id"], posting["version"])
    ctx["events"] = [
        new_telematics_event(
            ctx["driver"]["id"], "SEATBELT", 3, "2026-08-01T0%d:00:00Z" % (6 + index)
        )
        for index in range(events)
    ]
    return ctx


def test_two_seatbelt_events_move_nothing_beyond_the_drivers_own_counters(api):
    """PRD §3.9: "`coaching_hold` is true exactly when `safety_score` is strictly below 70,
    which is to say when open points exceed thirty."

    Design: Difficulty/transitive_cascade/coaching_hold_cascade_strips_planned_trip_orders_store_ledger_and_open_bids
    """
    ctx = _coaching_hold_cascade(events=2)
    assert ctx["events"][0]["penalty_points"] == 12
    driver = read_driver(ctx["driver"]["id"])
    assert driver["open_penalty_points"] == 24
    assert driver["safety_score"] == 76
    assert driver["coaching_hold"] is False
    trip = read_trip(ctx["trip"]["id"])
    assert trip["plan_status"] == "PLANNED"
    assert trip["driver_id"] == ctx["driver"]["id"]
    assert read_store(ctx["store"]["id"])["open_scheduled_cases"] == 900


def test_the_hold_flip_pushes_the_planned_trip_backwards_into_draft(api):
    """PRD §3.9: "Every trip of that driver whose `plan_status` is `DRAFT` or `PLANNED` is
    stripped: its `driver_id`, `tractor_id` and `trailer_id` are cleared to null, its
    `pinned_pay_plan_id` and `pinned_pay_plan_version` are cleared to null, its
    `planned_pay_cents` is reset to zero, and any trip that had reached `PLANNED` is
    pushed backwards to `DRAFT` — the one transition in the operations dimension that
    ever runs in reverse."

    Design: Difficulty/transitive_cascade/coaching_hold_cascade_strips_planned_trip_orders_store_ledger_and_open_bids
    """
    ctx = _coaching_hold_cascade()
    driver = read_driver(ctx["driver"]["id"])
    assert driver["open_penalty_points"] == 36
    assert driver["safety_score"] == 64
    assert driver["coaching_hold"] is True

    trip = read_trip(ctx["trip"]["id"])
    assert trip["plan_status"] == "DRAFT"
    assert trip["driver_id"] is None
    assert trip["tractor_id"] is None
    assert trip["trailer_id"] is None
    assert trip["pinned_pay_plan_id"] is None
    assert trip["pinned_pay_plan_version"] is None
    assert trip["planned_pay_cents"] == 0
    assert read_tractor(ctx["tractor"]["id"])["status"] == "AVAILABLE"
    assert get_success_data(api.get_trailer(ctx["trailer"]["id"], MAINTENANCE))["status"] == "AVAILABLE"
    # PRD §3.9 names only the trip's DELIVERY stops as the ones that go to SKIPPED.
    for stop in ctx["stops"]:
        if stop["stop_type"] != "DELIVERY":
            continue
        assert get_success_data(api.get_trip_stop(stop["id"], PLANNER))["status"] == "SKIPPED"


def test_the_stripped_trip_releases_its_order_and_that_lowers_the_store_ledger(api):
    """PRD §3.9: "Every `DELIVERY` stop on those trips releases its replenishment order
    `SCHEDULED → UNSCHEDULED`, each release lowering that store's `open_scheduled_cases`
    by the order's `cases`, and the stops themselves go to `SKIPPED`."

    Design: Difficulty/transitive_cascade/coaching_hold_cascade_strips_planned_trip_orders_store_ledger_and_open_bids
    """
    ctx = _coaching_hold_cascade()
    assert get_success_data(api.get_order(ctx["order"]["id"], PLANNER))["status"] == "UNSCHEDULED"
    assert read_store(ctx["store"]["id"])["open_scheduled_cases"] == 0


def test_the_same_flip_passes_over_the_drivers_open_bid(api):
    """PRD §3.9: "In parallel, every one of the driver's route bids still in `SUBMITTED` is
    moved to `PASSED_OVER`, and each such bid lowers its posting's `bid_count` by one."

    Design: Difficulty/transitive_cascade/coaching_hold_cascade_strips_planned_trip_orders_store_ledger_and_open_bids
    """
    ctx = _coaching_hold_cascade()
    assert get_success_data(api.get_route_bid(ctx["bid"]["id"], MANAGER))["status"] == "PASSED_OVER"
    assert read_posting(ctx["posting"]["id"])["bid_count"] == 0
    rows, meta = validate_paginated(
        api.list_telematics_events(SAFETY, {"driver_id": ctx["driver"]["id"]})
    )
    assert meta["total_count"] == 3
    assert all(row["coached"] is False for row in rows)


def _overstaffed_domicile():
    """DOM-KC carries three ACTIVE drivers against a headcount target of two."""
    set_clock()
    domicile = new_domicile(
        domicile_code="DOM-KC",
        region_code="MIDWEST",
        tractor_capacity=10,
        driver_headcount_target=2,
        fixed_ownership_cents_per_day=8000,
        overhead_cents_per_day=2500,
        dedicated_rate_cents_per_mile=290,
        dedicated_rate_cents_per_case=215,
    )
    pay_plan = new_pay_plan(
        plan_code="MILE-A",
        mileage_cents_per_mile=78,
        stop_cents_per_stop=2200,
        drop_hook_cents=1500,
        hourly_cents_per_minute=42,
        minimum_daily_cents=24000,
        backhaul_bonus_pct=0.05,
    )
    drivers = [
        new_driver(domicile["id"], pay_plan["id"], driver_code=code, seniority_date=seniority)
        for code, seniority in (("D-91", "2015-04-01"), ("D-92", "2018-04-01"), ("D-93", "2022-04-01"))
    ]
    before = get_success_data(api_client.get_domicile(domicile["id"], MANAGER))
    posting = new_route_posting(
        domicile["id"], headers=make_transport_manager_headers("user-tm-1"),
        route_code="RT-200", weekly_miles=1500, weekly_stops=10,
        start_effective_date="2026-09-01", bid_close_at="2026-08-10T00:00:00Z",
    )
    return {
        "domicile": domicile,
        "drivers": drivers,
        "leaver": drivers[2],
        "before": before,
        "posting": posting,
        "bid": place_bid(drivers[2]["id"], posting["id"], posting["version"]),
    }


def test_termination_lowers_the_active_headcount_and_re_derives_the_balance_index(api):
    """PRD §3.3: "The **balance index** is the domicile's staffing health: the count of that
    domicile's `ACTIVE` drivers divided by its `driver_headcount_target`, rounded half up
    to four decimal places."

    Design: Difficulty/transitive_cascade/driver_termination_cascades_to_open_bids_and_domicile_balance_index
    """
    ctx = _overstaffed_domicile()
    assert ctx["before"]["assigned_driver_count"] == 3
    assert ctx["before"]["balance_index"] == 1.5000

    terminated = get_success_data(
        api.terminate_driver(ctx["leaver"]["id"], {"termination_reason": "VOLUNTARY_QUIT"}, MANAGER)
    )
    assert terminated["status"] == "TERMINATED"
    after = get_success_data(api.get_domicile(ctx["domicile"]["id"], MANAGER))
    assert after["assigned_driver_count"] == 2
    assert after["balance_index"] == 1.0000

    rows, meta = validate_paginated(
        api.list_drivers(MANAGER, {"domicile_id": ctx["domicile"]["id"], "status": "ACTIVE"})
    )
    assert meta["total_count"] == 2
    assert ctx["leaver"]["id"] not in [row["id"] for row in rows]


def test_termination_passes_over_the_leavers_open_bid_but_leaves_the_posting_open(api):
    """PRD §3.3: "And every one of the driver's route bids still in `SUBMITTED` moves to
    `PASSED_OVER`, with each such bid lowering its posting's `bid_count` by 1."

    Design: Difficulty/transitive_cascade/driver_termination_cascades_to_open_bids_and_domicile_balance_index
    """
    ctx = _overstaffed_domicile()
    assert ctx["bid"]["status"] == "SUBMITTED"
    assert ctx["bid"]["seniority_date_snapshot"] == "2022-04-01"
    assert ctx["bid"]["safety_score_snapshot"] == 100

    get_success_data(api.terminate_driver(ctx["leaver"]["id"], {}, MANAGER))
    assert get_success_data(api.get_route_bid(ctx["bid"]["id"], MANAGER))["status"] == "PASSED_OVER"
    posting = read_posting(ctx["posting"]["id"])
    assert posting["bid_count"] == 0
    assert posting["status"] == "OPEN"


def test_terminated_is_terminal_so_a_second_walk_out_is_an_invalid_transition(api):
    """PRD §3.3: "`TERMINATED` is terminal, so a second termination is
    `ERR_INVALID_STATE_TRANSITION`, and so is a termination attempted while any trip
    references the driver in `PLANNED`, `DISPATCHED` or `IN_PROGRESS` — a driver cannot be
    walked out from under committed work."

    Design: Difficulty/transitive_cascade/driver_termination_cascades_to_open_bids_and_domicile_balance_index
    """
    ctx = _overstaffed_domicile()
    get_success_data(api.terminate_driver(ctx["leaver"]["id"], {}, MANAGER))
    validate_error(
        api.terminate_driver(ctx["leaver"]["id"], {}, MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    after = get_success_data(api.get_domicile(ctx["domicile"]["id"], MANAGER))
    assert after["assigned_driver_count"] == 2
    assert after["balance_index"] == 1.0000
