"""Error catalogue: per-entity 404s, declared-order body references and the guard ladder."""

from test_helpers import (
    MAINTENANCE,
    MANAGER,
    NON_EXISTENT_UUID,
    PAYROLL,
    PLANNER,
    SAFETY,
    ApiErrorId,
    add_delivery_stop,
    assign_resources,
    close_out_trip,
    coach_event,
    create_driver_payload,
    delivery_stop_payload,
    dispatch_trip,
    make_driver_headers,
    new_domicile,
    new_driver,
    new_order,
    new_pay_plan,
    new_route_posting,
    new_store,
    new_tractor,
    new_trailer,
    new_trip,
    new_telematics_event,
    new_work_order,
    non_delivery_stop_payload,
    plan_trip,
    read_driver,
    read_posting,
    read_tractor,
    read_trip,
    run_stop,
    set_clock,
    setup_base_fleet,
    validate_error,
    validate_paginated,
    validate_success,
)


# ------------------------------------------------- one 404 code per addressable entity ----


def test_every_addressable_entity_answers_with_its_own_not_found_code(api):
    """PRD §2.7: "**Existence of the addressed entity.** The row named by the final path
    parameter must exist. Applies to every endpoint that has a path parameter. The code is per
    entity: `ERR_STORE_NOT_FOUND`, `ERR_DOMICILE_NOT_FOUND`, `ERR_PAY_PLAN_NOT_FOUND`,
    `ERR_DRIVER_NOT_FOUND`, `ERR_TRACTOR_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`, `ERR_TRIP_STOP_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`,
    `ERR_POSTING_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`."

    Design: Corner/errors/every_addressable_entity_reports_its_own_not_found_code
    """
    set_clock()
    ghost = NON_EXISTENT_UUID
    probes = [
        (api.get_store(ghost, PLANNER), ApiErrorId.ERR_STORE_NOT_FOUND),
        (api.get_domicile(ghost, PLANNER), ApiErrorId.ERR_DOMICILE_NOT_FOUND),
        (api.get_pay_plan(ghost, PAYROLL), ApiErrorId.ERR_PAY_PLAN_NOT_FOUND),
        (api.get_driver(ghost, MANAGER), ApiErrorId.ERR_DRIVER_NOT_FOUND),
        (api.get_tractor(ghost, MAINTENANCE), ApiErrorId.ERR_TRACTOR_NOT_FOUND),
        (api.get_trailer(ghost, MAINTENANCE), ApiErrorId.ERR_TRAILER_NOT_FOUND),
        (api.get_order(ghost, PLANNER), ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api.get_trip(ghost, PLANNER), ApiErrorId.ERR_TRIP_NOT_FOUND),
        (api.get_trip_stop(ghost, PLANNER), ApiErrorId.ERR_TRIP_STOP_NOT_FOUND),
        (api.get_backhaul_offer(ghost, MANAGER), ApiErrorId.ERR_OFFER_NOT_FOUND),
        (api.get_work_order(ghost, MAINTENANCE), ApiErrorId.ERR_WORK_ORDER_NOT_FOUND),
        (api.get_pay_statement(ghost, PAYROLL), ApiErrorId.ERR_STATEMENT_NOT_FOUND),
        (api.get_route_posting(ghost, MANAGER), ApiErrorId.ERR_POSTING_NOT_FOUND),
        (api.get_route_bid(ghost, MANAGER), ApiErrorId.ERR_BID_NOT_FOUND),
        (api.get_telematics_event(ghost, SAFETY), ApiErrorId.ERR_EVENT_NOT_FOUND),
    ]
    for response, expected in probes:
        validate_error(response, expected, 404)


def test_a_child_listing_under_an_unknown_parent_reports_the_parent(api):
    """PRD §2.7: "**Existence of the addressed entity.** The row named by the final path
    parameter must exist. Applies to every endpoint that has a path parameter." And PRD §2.7:
    "This deliberately outranks existence, so a forbidden role probing a random UUID receives
    403 and never 404."

    Design: Corner/errors/every_addressable_entity_reports_its_own_not_found_code
    """
    set_clock()
    validate_error(
        api.list_stops_of_trip(NON_EXISTENT_UUID, PLANNER, {"limit": 10, "offset": 0}),
        ApiErrorId.ERR_TRIP_NOT_FOUND,
        404,
    )
    # A real trip with no stops is an empty page, not a 404 - the code above is the parent's.
    domicile = new_domicile(domicile_code="DOM-X1")
    empty = new_trip(domicile["id"], trip_code="TRIP-X1")
    rows, meta = validate_paginated(
        api.list_stops_of_trip(empty["id"], PLANNER, {"limit": 10, "offset": 0})
    )
    assert rows == []
    assert meta["total_count"] == 0


# ------------------------------------------ unresolvable body references, in field order ----


def _reference_probe_fixture():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-X2")
    plan = new_pay_plan(plan_code="MILE-C")
    driver = new_driver(domicile["id"], plan["id"], driver_code="D-X2")
    store = new_store(store_code="S-6020")
    order = new_order(store["id"])
    tractor = new_tractor(domicile["id"], unit_code="TR-X2")
    posting = new_route_posting(domicile["id"], route_code="P-X2")
    trip = new_trip(domicile["id"], trip_code="TRIP-X2",
                    planned_start_at="2026-08-20T06:00:00Z")
    return {"domicile": domicile, "plan": plan, "driver": driver, "store": store,
            "order": order, "tractor": tractor, "posting": posting, "trip": trip,
            "trip_v0": trip["version"]}


def test_the_first_unresolvable_reference_in_declared_order_is_the_one_reported(api):
    """PRD §2.7: "**Existence of body references.** Every foreign key supplied in a request body
    must resolve, using the same per-entity codes as level 4." And PRD §2.7: "When more than one
    reference is unresolvable, the reported code follows the order in which the body fields are
    declared for that operation in §4's companion narrative in §3."

    Design: Corner/errors/unresolvable_body_references_are_reported_in_declared_field_order
    """
    ctx = _reference_probe_fixture()
    # A driver is declared with its domicile before its pay plan.
    validate_error(
        api.create_driver(
            create_driver_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                                  driver_code="D-X2B", seniority_date="2020-01-01"),
            MANAGER,
        ),
        ApiErrorId.ERR_DOMICILE_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_driver(
            create_driver_payload(ctx["domicile"]["id"], NON_EXISTENT_UUID,
                                  driver_code="D-X2B", seniority_date="2020-01-01"),
            MANAGER,
        ),
        ApiErrorId.ERR_PAY_PLAN_NOT_FOUND,
        404,
    )
    # Crewing is declared driver, then tractor, then trailer.
    validate_error(
        api.assign_trip_resources(
            ctx["trip"]["id"],
            {"driver_id": ctx["driver"]["id"], "tractor_id": NON_EXISTENT_UUID,
             "trailer_id": NON_EXISTENT_UUID},
            MANAGER,
        ),
        ApiErrorId.ERR_TRACTOR_NOT_FOUND,
        404,
    )
    validate_error(
        api.assign_trip_resources(
            ctx["trip"]["id"],
            {"driver_id": ctx["driver"]["id"], "tractor_id": ctx["tractor"]["id"],
             "trailer_id": NON_EXISTENT_UUID},
            MANAGER,
        ),
        ApiErrorId.ERR_TRAILER_NOT_FOUND,
        404,
    )
    assert read_trip(ctx["trip"]["id"])["driver_id"] is None


def test_a_missing_reference_outranks_the_stale_version_guard(api):
    """PRD §2.7: "**Existence of body references.** Every foreign key supplied in a request body
    must resolve, using the same per-entity codes as level 4. This guards driver creation,
    tractor creation, trailer creation, replenishment-order creation, trip creation, stop append,
    trip assignment, backhaul linkage, pay-plan assignment, backhaul-offer creation, work-order
    creation, route-posting creation, bid placement, and telematics-event creation — fourteen
    operations in all." And PRD §2.7: "It runs after the entity's own state check and before
    every cross-entity check, so a stale version on an otherwise doomed request still returns
    412."

    Design: Corner/errors/unresolvable_body_references_are_reported_in_declared_field_order
    """
    ctx = _reference_probe_fixture()
    validate_error(
        api.add_trip_stop(
            ctx["trip"]["id"],
            delivery_stop_payload(1, ctx["store"]["id"], NON_EXISTENT_UUID,
                                  "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z",
                                  120, 100, 600),
            PLANNER,
        ),
        ApiErrorId.ERR_ORDER_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_route_bid(
            {"route_posting_id": NON_EXISTENT_UUID,
             "expected_posting_version": ctx["posting"]["version"]},
            make_driver_headers(ctx["driver"]["id"]),
        ),
        ApiErrorId.ERR_POSTING_NOT_FOUND,
        404,
    )
    validate_error(
        api.link_backhaul_offer(
            ctx["trip"]["id"],
            {"backhaul_offer_id": NON_EXISTENT_UUID,
             "expected_trip_version": ctx["trip_v0"]},
            MANAGER,
        ),
        ApiErrorId.ERR_OFFER_NOT_FOUND,
        404,
    )

    # Make the captured trip version stale with a real write, then replay it.
    add_delivery_stop(ctx["trip"]["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                      "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    validate_error(
        api.link_backhaul_offer(
            ctx["trip"]["id"],
            {"backhaul_offer_id": NON_EXISTENT_UUID,
             "expected_trip_version": ctx["trip_v0"]},
            MANAGER,
        ),
        ApiErrorId.ERR_OFFER_NOT_FOUND,
        404,
    )
    only_write = read_trip(ctx["trip"]["id"])
    assert only_write["stop_count"] == 1
    assert only_write["driver_id"] is None
    assert only_write["version"] > ctx["trip_v0"]


# ------------------------------------- one status field, two directions of refusal ----


def _assigned_tractor_and_a_waiting_work_order(api):
    set_clock()
    domicile = new_domicile(domicile_code="DOM-X3")
    plan = new_pay_plan(plan_code="MILE-C")
    store = new_store(store_code="S-6030")
    driver_a = new_driver(domicile["id"], plan["id"], driver_code="D-X3A")
    driver_b = new_driver(domicile["id"], plan["id"], driver_code="D-X3B",
                          seniority_date="2019-04-01")
    tractor = new_tractor(domicile["id"], unit_code="TR-X3")
    trailer_a = new_trailer(domicile["id"], trailer_code="TL-X3A")
    trailer_b = new_trailer(domicile["id"], trailer_code="TL-X3B")
    order_a = new_order(store["id"])
    order_b = new_order(store["id"], requested_window_start="2026-08-22T06:00:00Z",
                        requested_window_end="2026-08-22T18:00:00Z")
    trip_a = new_trip(domicile["id"], trip_code="TRIP-X3A",
                      planned_start_at="2026-08-20T06:00:00Z")
    add_delivery_stop(trip_a["id"], store["id"], order_a["id"], 1,
                      "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    trip_b = new_trip(domicile["id"], trip_code="TRIP-X3B",
                      planned_start_at="2026-08-22T06:00:00Z")
    add_delivery_stop(trip_b["id"], store["id"], order_b["id"], 1,
                      "2026-08-22T08:00:00Z", "2026-08-22T09:15:00Z", 120, 100, 600)
    assign_resources(trip_a["id"], driver_a["id"], tractor["id"], trailer_a["id"])
    assert read_tractor(tractor["id"])["status"] == "ASSIGNED"
    work_order = new_work_order(tractor_id=tractor["id"])
    assert work_order["status"] == "SCHEDULED"
    return {"tractor": tractor, "trailer_b": trailer_b, "driver_b": driver_b,
            "trip_a": trip_a, "trip_b": trip_b, "work_order": work_order}


def _claim_the_tractor(api, ctx):
    return api.assign_trip_resources(
        ctx["trip_b"]["id"],
        {"driver_id": ctx["driver_b"]["id"], "tractor_id": ctx["tractor"]["id"],
         "trailer_id": ctx["trailer_b"]["id"]},
        MANAGER,
    )


def test_an_assigned_tractor_is_refused_by_both_the_road_and_the_shop(api):
    """PRD §3.5: "**Asset availability** comes first among the cross-entity checks: a tractor or
    trailer that is not `AVAILABLE` is refused with `ERR_ASSET_NOT_AVAILABLE`, and a tractor
    whose `pm_hold` is true is refused with `ERR_TRACTOR_PM_HOLD`." And PRD §3.2: "Starting the
    work takes the order `SCHEDULED → IN_SHOP` and drives the asset itself `AVAILABLE →
    IN_SHOP`; if the asset is not `AVAILABLE` at that moment the request fails with
    `ERR_ASSET_NOT_AVAILABLE`."

    Design: Corner/errors/an_asset_that_is_not_available_refuses_both_the_road_and_the_shop
    """
    ctx = _assigned_tractor_and_a_waiting_work_order(api)
    validate_error(_claim_the_tractor(api, ctx), ApiErrorId.ERR_ASSET_NOT_AVAILABLE, 409)
    validate_error(
        api.start_work_order(ctx["work_order"]["id"], MAINTENANCE),
        ApiErrorId.ERR_ASSET_NOT_AVAILABLE,
        409,
    )
    assert read_tractor(ctx["tractor"]["id"])["status"] == "ASSIGNED"
    assert validate_success(api.get_work_order(ctx["work_order"]["id"], MAINTENANCE))["status"] == "SCHEDULED"


def test_the_shop_takes_the_released_tractor_and_then_holds_it(api):
    """PRD §3.7: "From `DRAFT`, cancellation takes the trip `DRAFT → CANCELLED`: every stop in
    `PLANNED` or `ARRIVED` moves to `SKIPPED`; the tractor and trailer, if non-null, return to
    `AVAILABLE`; and the trip's `driver_id`, `tractor_id` and `trailer_id` are all cleared to
    null." And PRD §3.5: "**Asset availability** comes first among the cross-entity checks: a tractor or
    trailer that is not `AVAILABLE` is refused with `ERR_ASSET_NOT_AVAILABLE`, and a tractor
    whose `pm_hold` is true is refused with `ERR_TRACTOR_PM_HOLD`."

    Design: Corner/errors/an_asset_that_is_not_available_refuses_both_the_road_and_the_shop
    """
    ctx = _assigned_tractor_and_a_waiting_work_order(api)
    cancelled = validate_success(
        api.cancel_trip(ctx["trip_a"]["id"], {"reason_code": "VOLUME_DROP"}, PLANNER)
    )
    assert cancelled["plan_status"] == "CANCELLED"
    assert read_tractor(ctx["tractor"]["id"])["status"] == "AVAILABLE"

    started = validate_success(api.start_work_order(ctx["work_order"]["id"], MAINTENANCE))
    assert started["status"] == "IN_SHOP"
    assert read_tractor(ctx["tractor"]["id"])["status"] == "IN_SHOP"

    # The same code now guards the opposite direction.
    validate_error(_claim_the_tractor(api, ctx), ApiErrorId.ERR_ASSET_NOT_AVAILABLE, 409)


# --------------------------------------------- the third HOS ceiling and its restart ----


def _trip_worth_one_hundred_ninety_five_duty_minutes():
    ctx = setup_base_fleet("x4")
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-X4",
                    planned_start_at="2026-08-20T06:00:00Z")
    add_delivery_stop(trip["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                      "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    return ctx, trip


def _crew(api, ctx, trip):
    return api.assign_trip_resources(
        trip["id"],
        {"driver_id": ctx["driver"]["id"], "tractor_id": ctx["tractor"]["id"],
         "trailer_id": ctx["trailer"]["id"]},
        MANAGER,
    )


def test_one_minute_over_the_rolling_weekly_ceiling_reports_the_weekly_code(api):
    """PRD §3.5: "The three comparisons then run in a pinned order — drive, then duty, then
    weekly — so a trip that busts two of the three reports the first one in that order. A
    projected drive figure of more than eleven hours is `ERR_HOS_DRIVE_LIMIT`; a projected daily
    duty figure of more than fourteen hours is `ERR_HOS_DUTY_LIMIT`; a projected rolling-weekly
    figure of more than seventy hours is `ERR_HOS_WEEKLY_LIMIT`." And PRD §3.3: "Separately, a
    duty-log correction accepts any subset of `drive_minutes_used_today`,
    `duty_minutes_used_today` and `weekly_on_duty_minutes`, overwrites exactly the counters
    supplied, leaves the omitted ones alone, re-derives `hos_status`, and advances the `version`."

    Design: Corner/errors/the_rolling_weekly_limit_is_strict_and_a_thirty_four_hour_restart_clears_it
    """
    ctx, trip = _trip_worth_one_hundred_ninety_five_duty_minutes()
    corrected = validate_success(
        api.adjust_duty_log(ctx["driver"]["id"], {"weekly_on_duty_minutes": 4006}, MANAGER)
    )
    assert corrected["weekly_on_duty_minutes"] == 4006
    assert corrected["drive_minutes_used_today"] == 0
    assert corrected["duty_minutes_used_today"] == 0

    # 4006 + 195 == 4201 while the drive and duty projections both clear their ceilings.
    validate_error(_crew(api, ctx, trip), ApiErrorId.ERR_HOS_WEEKLY_LIMIT, 422)
    assert read_trip(trip["id"])["driver_id"] is None


def test_exactly_seventy_hours_is_feasible_and_the_restart_zeroes_all_three(api):
    """PRD §3.5: "All three comparisons are strict: a projection landing exactly on a ceiling is
    feasible." And PRD §3.3: "A rest-period record takes a `reset_kind` of either `DAILY`, which
    zeroes `drive_minutes_used_today` and `duty_minutes_used_today`, or `WEEKLY` — the
    thirty-four-hour restart — which zeroes those two and `weekly_on_duty_minutes` as well;
    either way `hos_status` returns to `AVAILABLE` and the driver's `version` advances."

    Design: Corner/errors/the_rolling_weekly_limit_is_strict_and_a_thirty_four_hour_restart_clears_it
    """
    ctx, trip = _trip_worth_one_hundred_ninety_five_duty_minutes()
    validate_success(
        api.adjust_duty_log(ctx["driver"]["id"], {"weekly_on_duty_minutes": 4005}, MANAGER)
    )
    crewed = validate_success(_crew(api, ctx, trip))
    assert crewed["driver_id"] == ctx["driver"]["id"]
    assert crewed["planned_duty_minutes"] == 195

    # Assignment reserves capacity without consuming it.
    reserved = read_driver(ctx["driver"]["id"])
    assert reserved["weekly_on_duty_minutes"] == 4005
    assert reserved["hos_status"] == "AVAILABLE"

    restarted = validate_success(api.hos_reset(ctx["driver"]["id"], {"reset_kind": "WEEKLY"}, MANAGER))
    assert restarted["weekly_on_duty_minutes"] == 0
    assert restarted["drive_minutes_used_today"] == 0
    assert restarted["duty_minutes_used_today"] == 0
    assert restarted["hos_status"] == "AVAILABLE"


# ------------------------------------------------- the money objection is reported last ----


def _statement_worth_nothing(api):
    ctx = setup_base_fleet(
        "x5",
        pay_plan_overrides={"plan_code": "MILE-0", "mileage_cents_per_mile": 0,
                            "stop_cents_per_stop": 0, "drop_hook_cents": 0,
                            "hourly_cents_per_minute": 0, "minimum_daily_cents": 0,
                            "backhaul_bonus_pct": 0.0},
    )
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-X5",
                    planned_start_at="2026-08-20T06:00:00Z")
    stop = add_delivery_stop(trip["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                             "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    assign_resources(trip["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    committed = plan_trip(trip["id"])
    assert committed["planned_pay_cents"] == 0
    dispatch_trip(trip["id"])
    run_stop(stop["id"], ctx["driver"]["id"], cases_handled=600)
    closed = close_out_trip(trip["id"], 120, 195)
    assert closed["driver_pay_cents"] == 0
    assert closed["settlement_status"] == "ACCRUED"
    rows, _meta = validate_paginated(
        api.list_pay_statements(PAYROLL, {"trip_id": trip["id"], "limit": 10, "offset": 0})
    )
    statement = rows[0]
    assert statement["gross_cents"] == 0
    assert statement["status"] == "ACCRUED"
    return ctx, trip, statement


def test_a_zero_gross_statement_is_refused_only_by_the_fiscal_floor(api):
    """PRD §3.8: "A statement whose `gross_cents` is zero cannot be paid at all and is refused
    with `ERR_ZERO_PAY_SETTLEMENT`." And PRD §2.7: "Money objections are reported last of all —
    every structural, temporal and capacity complaint surfaces before them."

    Design: Corner/errors/a_statement_worth_nothing_cannot_be_settled
    """
    _ctx, trip, statement = _statement_worth_nothing(api)
    validate_error(
        api.settle_pay_statement(statement["id"],
                                 {"settlement_reference": "PAYRUN-2026-40"}, PAYROLL),
        ApiErrorId.ERR_ZERO_PAY_SETTLEMENT,
        422,
    )
    refused = validate_success(api.get_pay_statement(statement["id"], PAYROLL))
    assert refused["status"] == "ACCRUED"
    assert refused["settlement_reference"] is None
    assert read_trip(trip["id"])["settlement_status"] == "ACCRUED"


def test_reversal_carries_no_fiscal_floor_at_all(api):
    """PRD §3.8: "Reversal is the money unwind, a `PayrollAnalyst` act with an optional
    `reason_code`, and it is valid from either `ACCRUED` or `SETTLED`; both origins produce an
    identical cascade." And PRD §3.8: "And it drives the trip's payroll dimension to `ADJUSTED`
    while zeroing the trip's `driver_pay_cents`."

    Design: Corner/errors/a_statement_worth_nothing_cannot_be_settled
    """
    _ctx, trip, statement = _statement_worth_nothing(api)
    validate_error(
        api.settle_pay_statement(statement["id"],
                                 {"settlement_reference": "PAYRUN-2026-40"}, PAYROLL),
        ApiErrorId.ERR_ZERO_PAY_SETTLEMENT,
        422,
    )
    unwound = validate_success(
        api.reverse_pay_statement(statement["id"], {"reason_code": "PLAN_ERROR"}, PAYROLL)
    )
    assert unwound["status"] == "REVERSED"
    adjusted = read_trip(trip["id"])
    assert adjusted["settlement_status"] == "ADJUSTED"
    assert adjusted["driver_pay_cents"] == 0


# ---------------------------------------------- the hold outranks the score it comes from ----


def _driver_thirty_six_points_down():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-X6")
    plan = new_pay_plan(plan_code="MILE-C")
    store = new_store(store_code="S-6060")
    driver = new_driver(domicile["id"], plan["id"], driver_code="D-X6")
    tractor = new_tractor(domicile["id"], unit_code="TR-X6")
    trailer = new_trailer(domicile["id"], trailer_code="TL-X6")
    order = new_order(store["id"])
    posting = new_route_posting(domicile["id"], route_code="P-X6")
    trip = new_trip(domicile["id"], trip_code="TRIP-X6",
                    planned_start_at="2026-08-20T06:00:00Z")
    add_delivery_stop(trip["id"], store["id"], order["id"], 1, "2026-08-20T08:00:00Z",
                      "2026-08-20T09:15:00Z", 120, 100, 600)
    events = [
        new_telematics_event(driver["id"], "SEATBELT", 3, "2026-07-%dT14:00:00Z" % day)
        for day in (20, 22, 24)
    ]
    assert events[0]["penalty_points"] == 12
    return {"driver": driver, "tractor": tractor, "trailer": trailer, "trip": trip,
            "posting": posting, "events": events}


def test_the_coaching_hold_is_reported_ahead_of_the_score_it_derives_from(api):
    """PRD §3.9: "`safety_score` is one hundred less those open points, floored at zero so it
    never goes negative. `coaching_hold` is true exactly when `safety_score` is strictly below
    70, which is to say when open points exceed thirty." And PRD §3.5: "**Driver eligibility**
    follows, in its own fixed internal order: a driver whose `coaching_hold` is true is refused
    with `ERR_DRIVER_COACHING_HOLD`; failing that, a driver whose `safety_score` is below 80 is
    refused with `ERR_DRIVER_SAFETY_INELIGIBLE`; failing that, the domicile comparison runs."

    Design: Corner/errors/a_driver_on_coaching_hold_can_neither_drive_nor_bid_until_coached
    """
    ctx = _driver_thirty_six_points_down()
    held = read_driver(ctx["driver"]["id"])
    assert held["open_penalty_points"] == 36
    assert held["safety_score"] == 64  # also below the 80 bidding threshold
    assert held["coaching_hold"] is True

    validate_error(
        api.assign_trip_resources(
            ctx["trip"]["id"],
            {"driver_id": ctx["driver"]["id"], "tractor_id": ctx["tractor"]["id"],
             "trailer_id": ctx["trailer"]["id"]},
            MANAGER,
        ),
        ApiErrorId.ERR_DRIVER_COACHING_HOLD,
        422,
    )
    validate_error(
        api.create_route_bid(
            {"route_posting_id": ctx["posting"]["id"],
             "expected_posting_version": ctx["posting"]["version"]},
            make_driver_headers(ctx["driver"]["id"]),
        ),
        ApiErrorId.ERR_DRIVER_COACHING_HOLD,
        422,
    )
    assert read_posting(ctx["posting"]["id"])["bid_count"] == 0


def test_coaching_two_events_returns_the_road_and_the_board_together(api):
    """PRD §3.9: "Coaching sets the event's `coached` to true, stamps `coached_at` from the
    logical clock and `coached_by_user_id` from the acting `X-User-ID`, lowers the driver's
    `open_penalty_points` by that event's `penalty_points`, recomputes `safety_score`, and clears
    `coaching_hold` when the recomputed score reaches 70 or above." And PRD §3.9: "Each accepted
    bid records `seniority_date_snapshot` and `safety_score_snapshot`, copies of the driver's
    `seniority_date` and `safety_score` as they stood at bid time, kept for audit only."

    Design: Corner/errors/a_driver_on_coaching_hold_can_neither_drive_nor_bid_until_coached
    """
    ctx = _driver_thirty_six_points_down()
    assert coach_event(ctx["events"][0]["id"])["coached"] is True
    assert coach_event(ctx["events"][1]["id"])["coached"] is True

    cleared = read_driver(ctx["driver"]["id"])
    assert cleared["open_penalty_points"] == 12
    assert cleared["safety_score"] == 88
    assert cleared["coaching_hold"] is False

    crewed = validate_success(
        api.assign_trip_resources(
            ctx["trip"]["id"],
            {"driver_id": ctx["driver"]["id"], "tractor_id": ctx["tractor"]["id"],
             "trailer_id": ctx["trailer"]["id"]},
            MANAGER,
        )
    )
    assert crewed["driver_id"] == ctx["driver"]["id"]

    bid = validate_success(
        api.create_route_bid(
            {"route_posting_id": ctx["posting"]["id"],
             "expected_posting_version": read_posting(ctx["posting"]["id"])["version"]},
            make_driver_headers(ctx["driver"]["id"]),
        ),
        201,
    )
    assert bid["status"] == "SUBMITTED"
    assert bid["safety_score_snapshot"] == 88


# ------------------------------------------- a stop's references must match its own type ----


def _draft_trip_store_and_order():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-X7")
    store = new_store(store_code="S-6070")
    order = new_order(store["id"])
    trip = new_trip(domicile["id"], trip_code="TRIP-X7",
                    planned_start_at="2026-08-20T06:00:00Z")
    return store, order, trip


def test_a_delivery_needs_both_references_and_a_fuel_stop_neither(api):
    """PRD §3.4: "A `DELIVERY` stop must carry both `store_id` and `replenishment_order_id`;
    every other stop type must carry neither, and either shape violation is
    `ERR_REFERENTIAL_INCOMPLETE`."

    Design: Corner/errors/a_stop_whose_references_do_not_match_its_type_is_structurally_incomplete
    """
    store, order, trip = _draft_trip_store_and_order()
    without_order = delivery_stop_payload(1, store["id"], order["id"],
                                         "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z",
                                         120, 100, 600)
    without_order.pop("replenishment_order_id")
    validate_error(api.add_trip_stop(trip["id"], without_order, PLANNER),
                   ApiErrorId.ERR_REFERENTIAL_INCOMPLETE, 422)

    without_store = delivery_stop_payload(1, store["id"], order["id"],
                                         "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z",
                                         120, 100, 600)
    without_store.pop("store_id")
    validate_error(api.add_trip_stop(trip["id"], without_store, PLANNER),
                   ApiErrorId.ERR_REFERENTIAL_INCOMPLETE, 422)

    over_referenced = non_delivery_stop_payload(1, "FUEL", "2026-08-20T07:00:00Z",
                                               "2026-08-20T07:25:00Z", 20, 15)
    over_referenced["store_id"] = store["id"]
    validate_error(api.add_trip_stop(trip["id"], over_referenced, PLANNER),
                   ApiErrorId.ERR_REFERENTIAL_INCOMPLETE, 422)

    assert read_trip(trip["id"])["stop_count"] == 0


def test_the_correctly_shaped_pair_is_accepted_after_the_refusals(api):
    """PRD §3.4: "A `DELIVERY` stop must carry both `store_id` and `replenishment_order_id`;
    every other stop type must carry neither, and either shape violation is
    `ERR_REFERENTIAL_INCOMPLETE`." And PRD §3.4: "For a `DELIVERY`, take the stop's `cases`,
    multiply by 60, divide by the store's `cases_per_hour_unload_rate`, round the result **up**
    to a whole minute, and then add a fixed fifteen minutes of setup and paperwork at the dock."

    Design: Corner/errors/a_stop_whose_references_do_not_match_its_type_is_structurally_incomplete
    """
    store, order, trip = _draft_trip_store_and_order()
    over_referenced = non_delivery_stop_payload(1, "FUEL", "2026-08-20T07:00:00Z",
                                               "2026-08-20T07:25:00Z", 20, 15)
    over_referenced["replenishment_order_id"] = order["id"]
    validate_error(api.add_trip_stop(trip["id"], over_referenced, PLANNER),
                   ApiErrorId.ERR_REFERENTIAL_INCOMPLETE, 422)

    delivery = validate_success(
        api.add_trip_stop(
            trip["id"],
            delivery_stop_payload(1, store["id"], order["id"], "2026-08-20T08:00:00Z",
                                  "2026-08-20T09:15:00Z", 120, 100, 600),
            PLANNER,
        ),
        201,
    )
    assert delivery["service_minutes"] == 75

    fuel = validate_success(
        api.add_trip_stop(
            trip["id"],
            non_delivery_stop_payload(2, "FUEL", "2026-08-20T10:00:00Z",
                                      "2026-08-20T10:25:00Z", 20, 15),
            PLANNER,
        ),
        201,
    )
    assert fuel["store_id"] is None
    assert fuel["replenishment_order_id"] is None
    assert read_trip(trip["id"])["stop_count"] == 2
