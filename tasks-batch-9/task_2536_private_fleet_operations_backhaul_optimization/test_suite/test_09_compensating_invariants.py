"""Ledgers that must return exactly to where they started once the compensating act runs."""

from test_helpers import (
    MANAGER,
    PAYROLL,
    PLANNER,
    SAFETY,
    ApiErrorId,
    add_delivery_stop,
    api_client,
    assign_resources,
    charge_penalty_events,
    coach_event,
    get_success_data,
    new_domicile,
    new_driver,
    new_order,
    new_pay_plan,
    new_store,
    new_tractor,
    new_trailer,
    new_trip,
    plan_trip,
    read_driver,
    read_store,
    read_tractor,
    read_trip,
    set_clock,
    setup_f1,
    validate_error,
    validate_paginated,
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


def _one_planned_order_and_one_idle_order():
    """S-1012 carries two orders, but only the 900-case one is planned onto TRIP-W."""
    set_clock()
    store = new_store(store_code="S-1012", region_code="MIDWEST", dock_count=2,
                      cases_per_hour_unload_rate=600, dock_open_minute=0,
                      dock_close_minute=1439)
    domicile = new_domicile(domicile_code="DOM-MSP", region_code="MIDWEST", tractor_capacity=18,
                            driver_headcount_target=9, fixed_ownership_cents_per_day=9000,
                            overhead_cents_per_day=2800, dedicated_rate_cents_per_mile=268,
                            dedicated_rate_cents_per_case=194)
    pay_plan = new_pay_plan(**MILE_A)
    driver = new_driver(domicile["id"], pay_plan["id"], driver_code="D-110",
                        seniority_date="2011-08-08")
    tractor = new_tractor(domicile["id"], unit_code="TR-551", odometer_miles=10000,
                          pm_interval_miles=25000, pm_last_service_odometer=9000)
    trailer = new_trailer(domicile["id"], trailer_code="VAN-951", capacity_cases=1800)

    def order(cases, weight):
        return new_order(store["id"], cases=cases, weight_lbs=weight,
                         requested_window_start="2026-08-12T08:00:00Z",
                         requested_window_end="2026-08-12T14:00:00Z",
                         temperature_mode="DRY", priority=3)

    planned_order = order(900, 19500)
    idle_order = order(500, 11000)
    trip = new_trip(domicile["id"], trip_code="TRIP-W",
                    planned_start_at="2026-08-12T06:00:00Z")
    stop = add_delivery_stop(trip["id"], store["id"], planned_order["id"], 1,
                             "2026-08-12T09:00:00Z", "2026-08-12T10:45:00Z", 150, 150, 900)
    return {
        "store": store,
        "driver": driver,
        "tractor": tractor,
        "trailer": trailer,
        "planned_order": planned_order,
        "idle_order": idle_order,
        "trip": trip,
        "stop": stop,
    }


def _ledger(store_id):
    return read_store(store_id)["open_scheduled_cases"]


def test_the_case_ledger_leaves_and_returns_to_zero_across_the_whole_trip_life(api):
    """PRD §2.10: "`Store.open_scheduled_cases` equals the sum of `cases` over that store's
    replenishment orders currently in `SCHEDULED` status."

    Design: Difficulty/compensating_invariant/store_case_ledger_returns_to_zero_after_a_trip_cancel
    """
    ctx = _one_planned_order_and_one_idle_order()
    store_id = ctx["store"]["id"]
    assert ctx["store"]["open_scheduled_cases"] == 0
    assert _ledger(store_id) == 0

    assign_resources(ctx["trip"]["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    # Staffing commits no order, so the ledger is still empty.
    assert _ledger(store_id) == 0

    plan_trip(ctx["trip"]["id"])
    assert _ledger(store_id) == 900

    get_success_data(
        api.cancel_order(ctx["idle_order"]["id"], {"reason_code": "STORE_REQUEST"}, PLANNER)
    )
    assert _ledger(store_id) == 900

    get_success_data(api.cancel_trip(ctx["trip"]["id"], {"reason_code": "NO_DRIVER"}, PLANNER))
    assert _ledger(store_id) == 0
    # No stop was ever completed, so the delivered accumulator never moved at all.
    assert read_store(store_id)["delivered_cases_total"] == 0


def test_the_ledger_rises_because_the_order_turned_scheduled_not_because_plan_was_called(api):
    """PRD §3.5: "Every `DELIVERY` stop's order moves `UNSCHEDULED → SCHEDULED`, and each
    order that turned `SCHEDULED` raises its store's `open_scheduled_cases` by that order's
    `cases` — a two-link chain in which the ledger movement is caused by the order
    transition, not by the commitment call itself."

    Design: Difficulty/compensating_invariant/store_case_ledger_returns_to_zero_after_a_trip_cancel
    """
    ctx = _one_planned_order_and_one_idle_order()
    assign_resources(ctx["trip"]["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    plan_trip(ctx["trip"]["id"])

    planned_order = get_success_data(api.get_order(ctx["planned_order"]["id"], PLANNER))
    idle_order = get_success_data(api.get_order(ctx["idle_order"]["id"], PLANNER))
    assert planned_order["status"] == "SCHEDULED"
    # The second order sits at the same store and was never put on a stop.
    assert idle_order["status"] == "UNSCHEDULED"
    assert _ledger(ctx["store"]["id"]) == planned_order["cases"]
    assert _ledger(ctx["store"]["id"]) != planned_order["cases"] + idle_order["cases"]


def test_cancelling_an_unscheduled_order_moves_no_ledger_because_it_was_never_inside(api):
    """PRD §3.4: "The store's `open_scheduled_cases` does not move, because an
    `UNSCHEDULED` order was never inside the ledger's filter to begin with."

    Design: Difficulty/compensating_invariant/store_case_ledger_returns_to_zero_after_a_trip_cancel
    """
    ctx = _one_planned_order_and_one_idle_order()
    assign_resources(ctx["trip"]["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    plan_trip(ctx["trip"]["id"])
    before = _ledger(ctx["store"]["id"])

    cancelled = get_success_data(
        api.cancel_order(ctx["idle_order"]["id"], {"reason_code": "STORE_REQUEST"}, PLANNER)
    )
    assert cancelled["status"] == "CANCELLED"
    assert _ledger(ctx["store"]["id"]) == before == 900
    validate_error(
        api.cancel_order(ctx["planned_order"]["id"], {}, PLANNER),
        ApiErrorId.ERR_ORDER_NOT_SCHEDULABLE,
        409,
    )
    assert _ledger(ctx["store"]["id"]) == 900


def test_the_planned_cancel_cascade_unwinds_the_order_the_stop_and_the_tractor(api):
    """PRD §3.7: "From `PLANNED`, cancellation takes the trip `PLANNED → CANCELLED` with a
    longer chain: every stop in `PLANNED` or `ARRIVED` moves to `SKIPPED`; each stop that
    turned `SKIPPED` and carries a `replenishment_order_id` whose order is `SCHEDULED`
    drives that order `SCHEDULED → UNSCHEDULED`; each order that turned `UNSCHEDULED`
    lowers its store's `open_scheduled_cases` by its `cases`"

    Design: Difficulty/compensating_invariant/store_case_ledger_returns_to_zero_after_a_trip_cancel
    """
    ctx = _one_planned_order_and_one_idle_order()
    assign_resources(ctx["trip"]["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    plan_trip(ctx["trip"]["id"])
    assert read_tractor(ctx["tractor"]["id"])["status"] == "ASSIGNED"

    cancelled = get_success_data(
        api.cancel_trip(ctx["trip"]["id"], {"reason_code": "NO_DRIVER"}, PLANNER)
    )
    assert cancelled["plan_status"] == "CANCELLED"
    assert cancelled["driver_id"] is None
    assert cancelled["tractor_id"] is None
    assert cancelled["trailer_id"] is None

    assert get_success_data(api.get_order(ctx["planned_order"]["id"], PLANNER))["status"] == "UNSCHEDULED"
    assert get_success_data(api.get_trip_stop(ctx["stop"]["id"], PLANNER))["status"] == "SKIPPED"
    assert read_tractor(ctx["tractor"]["id"])["status"] == "AVAILABLE"
    assert _ledger(ctx["store"]["id"]) == 0


def _accrued_pay_cycle():
    """The canonical trip closed out on 335 drive and 560 duty minutes."""
    ctx = setup_f1(
        stage="completed",
        order_overrides={"weight_lbs": 19500},
        trip_overrides={"trip_code": "TRIP-F1"},
        actual_drive_minutes=335,
        actual_duty_minutes=560,
    )
    rows, meta = validate_paginated(
        api_client.list_pay_statements(PAYROLL, {"trip_id": ctx["trip"]["id"]})
    )
    assert meta["total_count"] == 1
    ctx["statement"] = rows[0]
    return ctx


def _pay_ledgers(ctx):
    domicile = get_success_data(api_client.get_domicile(ctx["domicile"]["id"], MANAGER))
    return domicile["accrued_pay_cents"], read_driver(ctx["driver"]["id"])["ytd_gross_cents"]


def test_close_out_raises_both_pay_ledgers_by_the_created_statements_gross(api):
    """PRD §3.8: "The created statement then raises the driver's domicile
    `accrued_pay_cents` by `gross_cents` and the driver's own `ytd_gross_cents` by
    `gross_cents` — a second link caused by the statement's creation."

    Design: Difficulty/compensating_invariant/pay_ledgers_unwind_exactly_on_statement_reversal
    """
    ctx = _accrued_pay_cycle()
    assert ctx["planned_trip"]["driver_pay_cents"] == 0
    assert ctx["planned_trip"]["settlement_status"] == "PENDING"
    assert ctx["stops"][0]["service_minutes"] == 105
    assert ctx["planned_trip"]["planned_duty_minutes"] == 505
    assert ctx["planned_trip"]["total_miles"] == 273
    assert ctx["planned_trip"]["planned_end_at"].startswith("2026-08-03T14:50:00")

    assert ctx["trip"]["plan_status"] == "COMPLETED"
    assert ctx["trip"]["settlement_status"] == "ACCRUED"
    assert ctx["trip"]["driver_pay_cents"] == 28244
    statement = ctx["statement"]
    assert statement["gross_cents"] == 28244
    assert statement["status"] == "ACCRUED"
    assert statement["variant"] == "FINAL_SETTLEMENT"
    assert statement["hourly_cents"] == 1050
    assert statement["guarantee_makeup_cents"] == 0
    assert _pay_ledgers(ctx) == (28244, 28244)


def test_settling_is_not_a_second_accrual_so_neither_ledger_moves(api):
    """PRD §3.8: "The domicile's `accrued_pay_cents` does **not** move on settlement,
    because both `ACCRUED` and `SETTLED` sit inside that ledger's status filter."

    Design: Difficulty/compensating_invariant/pay_ledgers_unwind_exactly_on_statement_reversal
    """
    ctx = _accrued_pay_cycle()
    assert _pay_ledgers(ctx) == (28244, 28244)

    settled = get_success_data(
        api.settle_pay_statement(
            ctx["statement"]["id"], {"settlement_reference": "ACH-2026-0912"}, PAYROLL
        )
    )
    assert settled["status"] == "SETTLED"
    assert settled["gross_cents"] == 28244
    assert read_trip(ctx["trip"]["id"])["settlement_status"] == "SETTLED"
    assert _pay_ledgers(ctx) == (28244, 28244)


def test_reversal_returns_both_ledgers_to_zero_without_disturbing_the_plan_dimension(api):
    """PRD §3.8: "That reversal then lowers the domicile's `accrued_pay_cents` by the
    statement's `gross_cents` and lowers the driver's `ytd_gross_cents` by the same amount.
    And it drives the trip's payroll dimension to `ADJUSTED` while zeroing the trip's
    `driver_pay_cents`."

    Design: Difficulty/compensating_invariant/pay_ledgers_unwind_exactly_on_statement_reversal
    """
    ctx = _accrued_pay_cycle()
    get_success_data(
        api.settle_pay_statement(
            ctx["statement"]["id"], {"settlement_reference": "ACH-2026-0912"}, PAYROLL
        )
    )
    reversed_statement = get_success_data(
        api.reverse_pay_statement(ctx["statement"]["id"], {"reason_code": "OVERPAYMENT"}, PAYROLL)
    )
    assert reversed_statement["status"] == "REVERSED"
    # The reversal writes off the money it once created, to the cent.
    assert reversed_statement["gross_cents"] == 28244
    assert _pay_ledgers(ctx) == (0, 0)

    unwound = read_trip(ctx["trip"]["id"])
    assert unwound["settlement_status"] == "ADJUSTED"
    assert unwound["driver_pay_cents"] == 0
    assert unwound["plan_status"] == "COMPLETED"


def _three_seatbelt_exceptions():
    """D-120 collects three identical severity-3 seatbelt events worth twelve points each."""
    set_clock()
    domicile = new_domicile(domicile_code="DOM-KC", region_code="MIDWEST", tractor_capacity=16,
                            driver_headcount_target=8, fixed_ownership_cents_per_day=8800,
                            overhead_cents_per_day=2600, dedicated_rate_cents_per_mile=265,
                            dedicated_rate_cents_per_case=192)
    pay_plan = new_pay_plan(**MILE_A)
    driver = new_driver(domicile["id"], pay_plan["id"], driver_code="D-120",
                        seniority_date="2010-05-05")
    assert driver["open_penalty_points"] == 0
    assert driver["safety_score"] == 100
    assert driver["coaching_hold"] is False

    events = charge_penalty_events(
        driver["id"],
        [
            ("SEATBELT", 3, "2026-07-10T09:00:00Z"),
            ("SEATBELT", 3, "2026-07-11T09:00:00Z"),
            ("SEATBELT", 3, "2026-07-12T09:00:00Z"),
        ],
    )
    return {"driver": driver, "events": events}


def test_the_score_is_one_hundred_less_the_open_points_at_every_step_down(api):
    """PRD §3.9: "`safety_score` is one hundred less those open points, floored at zero so
    it never goes negative."

    Design: Difficulty/compensating_invariant/safety_score_and_open_penalty_points_always_sum_to_one_hundred
    """
    ctx = _three_seatbelt_exceptions()
    assert [event["penalty_points"] for event in ctx["events"]] == [12, 12, 12]
    standing = read_driver(ctx["driver"]["id"])
    assert standing["open_penalty_points"] == 36
    assert standing["safety_score"] == 64
    assert standing["open_penalty_points"] + standing["safety_score"] == 100


def test_the_hold_flips_only_once_the_open_points_pass_thirty(api):
    """PRD §3.9: "`coaching_hold` is true exactly when `safety_score` is strictly below 70,
    which is to say when open points exceed thirty."

    Design: Difficulty/compensating_invariant/safety_score_and_open_penalty_points_always_sum_to_one_hundred
    """
    set_clock()
    domicile = new_domicile(domicile_code="DOM-KC", region_code="MIDWEST", tractor_capacity=16,
                            driver_headcount_target=8, fixed_ownership_cents_per_day=8800,
                            overhead_cents_per_day=2600, dedicated_rate_cents_per_mile=265,
                            dedicated_rate_cents_per_case=192)
    pay_plan = new_pay_plan(**MILE_A)
    driver = new_driver(domicile["id"], pay_plan["id"], driver_code="D-120",
                        seniority_date="2010-05-05")

    observations = []
    for day in ("10", "11", "12"):
        charge_penalty_events(driver["id"], [("SEATBELT", 3, "2026-07-%sT09:00:00Z" % day)])
        standing = read_driver(driver["id"])
        observations.append(
            (standing["open_penalty_points"], standing["safety_score"], standing["coaching_hold"])
        )
    assert observations == [(12, 88, False), (24, 76, False), (36, 64, True)]


def test_coaching_restores_exactly_the_points_the_event_carried_and_lifts_the_hold(api):
    """PRD §3.9: "Coaching sets the event's `coached` to true, stamps `coached_at` from the
    logical clock and `coached_by_user_id` from the acting `X-User-ID`, lowers the driver's
    `open_penalty_points` by that event's `penalty_points`, recomputes `safety_score`, and
    clears `coaching_hold` when the recomputed score reaches 70 or above."

    Design: Difficulty/compensating_invariant/safety_score_and_open_penalty_points_always_sum_to_one_hundred
    """
    ctx = _three_seatbelt_exceptions()
    coached = coach_event(ctx["events"][0]["id"], note="Belt discipline reviewed in cab.")
    assert coached["coached"] is True
    # The points stay recorded on the event; only the driver's open sum moves.
    assert coached["penalty_points"] == 12
    assert coached["coached_by_user_id"] == SAFETY["X-User-ID"]

    standing = read_driver(ctx["driver"]["id"])
    assert standing["open_penalty_points"] == 24
    assert standing["safety_score"] == 76
    assert standing["coaching_hold"] is False
    assert standing["open_penalty_points"] + standing["safety_score"] == 100


def test_coaching_is_terminal_so_the_points_cannot_be_restored_twice(api):
    """PRD §3.9: "The event must not already be coached — a second attempt is
    `ERR_ALREADY_COACHED` — and the driver must not be `TERMINATED`, which is
    `ERR_DRIVER_NOT_ACTIVE`."

    Design: Difficulty/compensating_invariant/safety_score_and_open_penalty_points_always_sum_to_one_hundred
    """
    ctx = _three_seatbelt_exceptions()
    coach_event(ctx["events"][0]["id"], note="Belt discipline reviewed in cab.")
    validate_error(
        api.coach_telematics_event(
            ctx["events"][0]["id"], {"coaching_note": "again"}, SAFETY
        ),
        ApiErrorId.ERR_ALREADY_COACHED,
        409,
    )
    standing = read_driver(ctx["driver"]["id"])
    assert standing["open_penalty_points"] == 24
    assert standing["safety_score"] == 76
    still_coached = get_success_data(api.get_telematics_event(ctx["events"][0]["id"], SAFETY))
    assert still_coached["coached"] is True
    assert still_coached["penalty_points"] == 12
