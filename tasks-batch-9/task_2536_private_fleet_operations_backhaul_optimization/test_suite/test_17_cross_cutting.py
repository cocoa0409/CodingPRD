"""Cross-cutting layers: the three stale-version guards, cascade atomicity and re-derivation."""

from test_helpers import (
    MAINTENANCE,
    MANAGER,
    PAYROLL,
    PLANNER,
    SAFETY,
    ApiErrorId,
    add_delivery_stop,
    add_other_stop,
    adjust_duty_log,
    api_client,
    assign_resources,
    dispatch_trip,
    make_driver_headers,
    new_backhaul_offer,
    new_domicile,
    new_driver,
    new_order,
    new_pay_plan,
    new_route_posting,
    new_store,
    new_telematics_event,
    new_tractor,
    new_trailer,
    new_trip,
    place_bid,
    plan_trip,
    read_driver,
    read_posting,
    read_store,
    read_tractor,
    read_trip,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


# ------------------------------------------- the trip version moves for unrelated reasons ----


def _draft_trip_and_two_proposed_offers():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-C1")
    plan = new_pay_plan(plan_code="MILE-C")
    store = new_store(store_code="S-6200")
    driver = new_driver(domicile["id"], plan["id"], driver_code="D-C1")
    tractor = new_tractor(domicile["id"], unit_code="TR-C1")
    trailer = new_trailer(domicile["id"], trailer_code="TL-C1")
    order = new_order(store["id"])
    trip = new_trip(domicile["id"], trip_code="TRIP-C1",
                    planned_start_at="2026-08-20T06:00:00Z")
    assert trip["version"] == 1
    offer_a = new_backhaul_offer(store["id"], shipper_name="Cross Layer Foods",
                                offer_expires_at="2026-08-18T00:00:00Z")
    offer_b = new_backhaul_offer(store["id"], origin_kind="THIRD_PARTY",
                                shipper_name="Cross Layer Logistics", revenue_cents=70000,
                                cases=400, weight_lbs=9000,
                                offer_expires_at="2026-08-18T00:00:00Z")
    add_delivery_stop(trip["id"], store["id"], order["id"], 1, "2026-08-20T08:00:00Z",
                      "2026-08-20T09:15:00Z", 120, 100, 600)
    read_at = read_trip(trip["id"])["version"]
    assert read_at == 2
    staffed = assign_resources(trip["id"], driver["id"], tractor["id"], trailer["id"])
    assert staffed["version"] == 3
    return {"trip": trip, "offer_a": offer_a, "offer_b": offer_b, "read_at": read_at}


def test_a_version_read_before_staffing_no_longer_links_a_backhaul(api):
    """PRD §2.8: "Linking a backhaul offer to a trip requires `expected_trip_version`, carrying
    the client's last observed `version` of that `Trip`." And PRD §2.8: "If it does not equal the
    trip's current `version`, the link is rejected with `ERR_STALE_TRIP_VERSION` (HTTP 412)." And
    PRD §2.4: "Most resources additionally carry `updated_at`, in the same timestamp format,
    refreshed on every mutation, and `version`, an integer that begins at 1 when the row is
    created and increases by exactly 1 on each mutation of that row."

    Design: Corner/cross_cutting_complexity_layers/linking_a_backhaul_offer_is_guarded_by_the_trip_version_it_was_read_at
    """
    ctx = _draft_trip_and_two_proposed_offers()
    validate_error(
        api.link_backhaul_offer(
            ctx["trip"]["id"],
            {"backhaul_offer_id": ctx["offer_a"]["id"],
             "expected_trip_version": ctx["read_at"]},
            MANAGER,
        ),
        ApiErrorId.ERR_STALE_TRIP_VERSION,
        412,
    )
    unchanged = read_trip(ctx["trip"]["id"])
    assert unchanged["backhaul_offer_id"] is None
    assert unchanged["version"] == 3

    linked = validate_success(
        api.link_backhaul_offer(
            ctx["trip"]["id"],
            {"backhaul_offer_id": ctx["offer_a"]["id"], "expected_trip_version": 3},
            MANAGER,
        )
    )
    assert linked["backhaul_offer_id"] == ctx["offer_a"]["id"]
    assert linked["backhaul_credit_cents"] == 0
    assert linked["version"] == 4


def test_the_stale_guard_runs_before_the_supersession_it_protects(api):
    """PRD §2.8: "The guard exists because linking legitimately supersedes whatever offer the trip
    already carried — the displaced offer is unlinked and, if it had been accepted, returned to the
    market — so a writer reasoning from an outdated read of the trip would silently discard a link
    it never saw." And PRD §3.6: "An offer already linked to a *different* trip is
    `ERR_BACKHAUL_ALREADY_LINKED`; the trip's own current link is never a conflict, because
    re-linking is designed to supersede it."

    Design: Corner/cross_cutting_complexity_layers/linking_a_backhaul_offer_is_guarded_by_the_trip_version_it_was_read_at
    """
    ctx = _draft_trip_and_two_proposed_offers()
    validate_success(
        api.link_backhaul_offer(
            ctx["trip"]["id"],
            {"backhaul_offer_id": ctx["offer_a"]["id"], "expected_trip_version": 3},
            MANAGER,
        )
    )
    # The holder of the pre-link version cannot displace an offer it never saw.
    validate_error(
        api.link_backhaul_offer(
            ctx["trip"]["id"],
            {"backhaul_offer_id": ctx["offer_b"]["id"], "expected_trip_version": 3},
            MANAGER,
        ),
        ApiErrorId.ERR_STALE_TRIP_VERSION,
        412,
    )
    held = read_trip(ctx["trip"]["id"])
    assert held["backhaul_offer_id"] == ctx["offer_a"]["id"]
    assert held["version"] == 4

    superseded = validate_success(
        api.link_backhaul_offer(
            ctx["trip"]["id"],
            {"backhaul_offer_id": ctx["offer_b"]["id"], "expected_trip_version": 4},
            MANAGER,
        )
    )
    assert superseded["backhaul_offer_id"] == ctx["offer_b"]["id"]
    assert superseded["version"] == 5


# ------------------------------------------------ the board moves under its own bidders ----


def _board_and_three_bidders():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-C2")
    plan = new_pay_plan(plan_code="MILE-C")
    driver_a = new_driver(domicile["id"], plan["id"], driver_code="D-C2A",
                          seniority_date="2019-03-01")
    driver_b = new_driver(domicile["id"], plan["id"], driver_code="D-C2B",
                          seniority_date="2018-03-01")
    driver_c = new_driver(domicile["id"], plan["id"], driver_code="D-C2C",
                          seniority_date="2017-03-01")
    posting = new_route_posting(domicile["id"], route_code="P-C2")
    assert posting["version"] == 1
    assert posting["bid_count"] == 0
    return domicile, posting, (driver_a, driver_b, driver_c)


def test_a_bidder_who_read_the_board_one_bid_ago_is_refused(api):
    """PRD §2.8: "Placing a bid on a route posting requires `expected_posting_version`, carrying
    the client's last observed `version` of that `RoutePosting`." And PRD §2.8: "A mismatch with
    the posting's current `version` is rejected with `ERR_STALE_POSTING_VERSION` (HTTP 412)." And
    PRD §3.9: "Creation raises the posting's `bid_count` by one and its `version` by one."

    Design: Corner/cross_cutting_complexity_layers/a_bid_is_guarded_by_the_board_version_that_other_bidders_keep_moving
    """
    _domicile, posting, drivers = _board_and_three_bidders()
    driver_a, driver_b, _driver_c = drivers
    first = place_bid(driver_a["id"], posting["id"], 1)
    assert first["status"] == "SUBMITTED"
    moved = read_posting(posting["id"])
    assert moved["version"] == 2
    assert moved["bid_count"] == 1

    validate_error(
        api.create_route_bid(
            {"route_posting_id": posting["id"], "expected_posting_version": 1},
            make_driver_headers(driver_b["id"]),
        ),
        ApiErrorId.ERR_STALE_POSTING_VERSION,
        412,
    )
    still = read_posting(posting["id"])
    assert still["version"] == 2
    assert still["bid_count"] == 1
    rows, meta = validate_paginated(
        api.list_route_bids(MANAGER, {"route_posting_id": posting["id"], "limit": 50,
                                      "offset": 0})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]

    second = place_bid(driver_b["id"], posting["id"], 2)
    assert second["status"] == "SUBMITTED"
    after_two = read_posting(posting["id"])
    assert after_two["version"] == 3
    assert after_two["bid_count"] == 2


def test_a_withdrawal_invalidates_the_board_version_just_as_a_bid_does(api):
    """PRD §3.9: "A driver may withdraw their own bid — anyone else's is
    `ERR_DRIVER_SCOPE_VIOLATION` — which moves it `SUBMITTED → WITHDRAWN`, lowers the posting's
    `bid_count` by one, and advances the posting's `version`." And PRD §3.9: "Each accepted bid
    records `seniority_date_snapshot` and `safety_score_snapshot`, copies of the driver's
    `seniority_date` and `safety_score` as they stood at bid time, kept for audit only."

    Design: Corner/cross_cutting_complexity_layers/a_bid_is_guarded_by_the_board_version_that_other_bidders_keep_moving
    """
    _domicile, posting, drivers = _board_and_three_bidders()
    driver_a, driver_b, driver_c = drivers
    first = place_bid(driver_a["id"], posting["id"], 1)
    place_bid(driver_b["id"], posting["id"], 2)

    pulled = validate_success(
        api.withdraw_route_bid(first["id"], make_driver_headers(driver_a["id"]))
    )
    assert pulled["status"] == "WITHDRAWN"
    after_withdrawal = read_posting(posting["id"])
    assert after_withdrawal["version"] == 4
    assert after_withdrawal["bid_count"] == 1

    validate_error(
        api.create_route_bid(
            {"route_posting_id": posting["id"], "expected_posting_version": 3},
            make_driver_headers(driver_c["id"]),
        ),
        ApiErrorId.ERR_STALE_POSTING_VERSION,
        412,
    )
    late = place_bid(driver_c["id"], posting["id"], 4)
    assert late["seniority_date_snapshot"] == "2017-03-01"
    assert late["safety_score_snapshot"] == 100


# ------------------------------------- the driver row has three writers and one guard ----


def _driver_read_by_payroll_before_two_other_writers():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-C3")
    plan_c = new_pay_plan(plan_code="MILE-C")
    plan_d = new_pay_plan(plan_code="MILE-D", mileage_cents_per_mile=120)
    store = new_store(store_code="S-6220")
    driver = new_driver(domicile["id"], plan_c["id"], driver_code="D-C3")
    assert driver["version"] == 1
    tractor = new_tractor(domicile["id"], unit_code="TR-C3")
    trailer = new_trailer(domicile["id"], trailer_code="TL-C3")
    order = new_order(store["id"])
    trip = new_trip(domicile["id"], trip_code="TRIP-C3",
                    planned_start_at="2026-08-20T06:00:00Z")
    add_delivery_stop(trip["id"], store["id"], order["id"], 1, "2026-08-20T08:00:00Z",
                      "2026-08-20T09:15:00Z", 120, 100, 600)
    assign_resources(trip["id"], driver["id"], tractor["id"], trailer["id"])
    committed = plan_trip(trip["id"])
    assert committed["pinned_pay_plan_id"] == plan_c["id"]
    assert committed["pinned_pay_plan_version"] == plan_c["version"]
    return {"plan_c": plan_c, "plan_d": plan_d, "driver": driver, "trip": trip,
            "planned_pay": committed["planned_pay_cents"],
            "read_at": read_driver(driver["id"], PAYROLL)["version"]}


def test_a_duty_correction_and_a_telematics_event_each_stale_the_payroll_read(api):
    """PRD §2.8: "Assigning a pay plan to a driver requires `expected_driver_version`, carrying
    the client's last observed `version` of that `Driver`." And PRD §2.8: "A mismatch with the
    driver's current `version` is rejected with `ERR_STALE_DRIVER_VERSION` (HTTP 412)." And PRD
    §3.3: "Separately, a duty-log correction accepts any subset of `drive_minutes_used_today`,
    `duty_minutes_used_today` and `weekly_on_duty_minutes`, overwrites exactly the counters
    supplied, leaves the omitted ones alone, re-derives `hos_status`, and advances the `version`."

    Design: Corner/cross_cutting_complexity_layers/a_pay_plan_assignment_is_guarded_by_the_driver_version_and_spares_pinned_trips
    """
    ctx = _driver_read_by_payroll_before_two_other_writers()
    assert ctx["read_at"] == 1
    corrected = adjust_duty_log(ctx["driver"]["id"], duty_minutes_used_today=120)
    assert corrected["version"] == 2

    validate_error(
        api.assign_pay_plan(
            ctx["driver"]["id"],
            {"pay_plan_id": ctx["plan_d"]["id"], "expected_driver_version": ctx["read_at"]},
            PAYROLL,
        ),
        ApiErrorId.ERR_STALE_DRIVER_VERSION,
        412,
    )
    new_telematics_event(ctx["driver"]["id"], "HARD_BRAKE", 1, "2026-07-20T14:00:00Z")
    after_event = read_driver(ctx["driver"]["id"], PAYROLL)
    assert after_event["version"] == 3
    assert after_event["open_penalty_points"] == 2
    assert after_event["pay_plan_id"] == ctx["plan_c"]["id"]

    # Version 2 is stale in its turn: the safety write moved the row again.
    validate_error(
        api.assign_pay_plan(
            ctx["driver"]["id"],
            {"pay_plan_id": ctx["plan_d"]["id"], "expected_driver_version": 2},
            PAYROLL,
        ),
        ApiErrorId.ERR_STALE_DRIVER_VERSION,
        412,
    )
    swapped = validate_success(
        api.assign_pay_plan(
            ctx["driver"]["id"],
            {"pay_plan_id": ctx["plan_d"]["id"], "expected_driver_version": 3},
            PAYROLL,
        )
    )
    assert swapped["pay_plan_id"] == ctx["plan_d"]["id"]
    assert swapped["version"] == 4


def test_the_swap_never_re_prices_a_trip_that_already_pinned_its_plan(api):
    """PRD §3.3: "What does *not* happen is any change to a trip that has already pinned a plan —
    a superseded plan continues to govern every trip that snapshotted it." And PRD §3.8: "Either
    variant may also be evaluated on demand, without persisting anything, by naming it in a
    `variant` parameter on the trip's pay preview; that read returns the `variant` it evaluated,
    the `pay_plan_id` and `pay_plan_version` it used, and the full breakdown as `mileage_cents`,
    `activity_cents`, `hourly_cents`, `bonus_cents`, `subtotal_cents`, `guarantee_makeup_cents`
    and `gross_cents`."

    Design: Corner/cross_cutting_complexity_layers/a_pay_plan_assignment_is_guarded_by_the_driver_version_and_spares_pinned_trips
    """
    ctx = _driver_read_by_payroll_before_two_other_writers()
    adjust_duty_log(ctx["driver"]["id"], duty_minutes_used_today=120)
    new_telematics_event(ctx["driver"]["id"], "HARD_BRAKE", 1, "2026-07-20T14:00:00Z")
    validate_success(
        api.assign_pay_plan(
            ctx["driver"]["id"],
            {"pay_plan_id": ctx["plan_d"]["id"], "expected_driver_version": 3},
            PAYROLL,
        )
    )
    pinned = read_trip(ctx["trip"]["id"], PAYROLL)
    assert pinned["pinned_pay_plan_id"] == ctx["plan_c"]["id"]
    assert pinned["pinned_pay_plan_version"] == ctx["plan_c"]["version"]
    assert pinned["planned_pay_cents"] == ctx["planned_pay"]

    preview = validate_success(
        api.get_pay_preview(ctx["trip"]["id"], PAYROLL, {"variant": "PLANNED_ACCRUAL"})
    )
    assert preview["pay_plan_id"] == ctx["plan_c"]["id"]
    assert preview["mileage_cents"] == 8000


# ------------------------------------------- the widest cascade fires all or not at all ----


def _trip_with_one_stop_still_only_arrived():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-C4")
    plan = new_pay_plan(plan_code="MILE-C")
    store = new_store(store_code="S-6240")
    driver = new_driver(domicile["id"], plan["id"], driver_code="D-C4")
    tractor = new_tractor(domicile["id"], unit_code="TR-C4")
    trailer = new_trailer(domicile["id"], trailer_code="TL-C4")
    order_one = new_order(store["id"], cases=400, weight_lbs=8800)
    order_two = new_order(store["id"], cases=200, weight_lbs=4400)
    trip = new_trip(domicile["id"], trip_code="TRIP-C4",
                    planned_start_at="2026-08-20T06:00:00Z")
    stop_one = add_delivery_stop(trip["id"], store["id"], order_one["id"], 1,
                                 "2026-08-20T08:00:00Z", "2026-08-20T08:55:00Z", 120, 100, 400)
    stop_two = add_delivery_stop(trip["id"], store["id"], order_two["id"], 2,
                                 "2026-08-20T10:00:00Z", "2026-08-20T10:35:00Z", 40, 30, 200)
    assign_resources(trip["id"], driver["id"], tractor["id"], trailer["id"])
    committed = plan_trip(trip["id"])
    assert committed["total_miles"] == 130
    assert committed["planned_duty_minutes"] == 250
    dispatch_trip(trip["id"])
    crew = make_driver_headers(driver["id"])
    validate_success(api_client.arrive_at_stop(stop_one["id"], crew))
    validate_success(api_client.complete_stop(stop_one["id"], {"cases_handled": 400}, crew))
    only_arrived = validate_success(api_client.arrive_at_stop(stop_two["id"], crew))
    assert only_arrived["status"] == "ARRIVED"
    return {"domicile": domicile, "store": store, "driver": driver, "tractor": tractor,
            "order_one": order_one, "trip": trip, "stop_two": stop_two, "crew": crew}


def test_a_close_out_refused_for_one_arrived_stop_applies_no_link_of_the_cascade(api):
    """PRD §3.7: "The trip must be `IN_PROGRESS` and every one of its stops must already be in a
    terminal stop status, that is `COMPLETED` or `SKIPPED`; either failure is
    `ERR_INVALID_STATE_TRANSITION`, and a `Driver` closing someone else's trip is
    `ERR_DRIVER_SCOPE_VIOLATION`." And PRD §2.10: "A cascade never stops halfway." And PRD §2.10:
    "If the operation is rejected at any precedence level, none of the links fire at all."

    Design: Corner/cross_cutting_complexity_layers/a_refused_close_out_leaves_every_link_of_the_cascade_unapplied
    """
    ctx = _trip_with_one_stop_still_only_arrived()
    validate_error(
        api.complete_trip(ctx["trip"]["id"],
                          {"actual_drive_minutes": 160, "actual_duty_minutes": 255}, MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    frozen = read_trip(ctx["trip"]["id"])
    assert frozen["plan_status"] == "IN_PROGRESS"
    assert frozen["settlement_status"] == "PENDING"
    assert frozen["driver_pay_cents"] == 0
    assert frozen["delivered_cases"] == 0

    assert validate_success(api.get_order(ctx["order_one"]["id"], PLANNER))["status"] == "SCHEDULED"
    ledger = read_store(ctx["store"]["id"])
    assert ledger["open_scheduled_cases"] == 600
    assert ledger["delivered_cases_total"] == 0

    crew_row = read_driver(ctx["driver"]["id"])
    assert crew_row["drive_minutes_used_today"] == 0
    assert crew_row["ytd_gross_cents"] == 0

    unit = read_tractor(ctx["tractor"]["id"])
    assert unit["odometer_miles"] == 50000
    assert unit["miles_since_pm"] == 10000
    assert unit["status"] == "ASSIGNED"

    _rows, statement_meta = validate_paginated(
        api.list_pay_statements(PAYROLL, {"trip_id": ctx["trip"]["id"], "limit": 10,
                                          "offset": 0})
    )
    assert statement_meta["total_count"] == 0
    _orders, work_order_meta = validate_paginated(
        api.list_work_orders(MAINTENANCE, {"tractor_id": ctx["tractor"]["id"], "limit": 10,
                                           "offset": 0})
    )
    assert work_order_meta["total_count"] == 0


def test_the_same_call_fires_every_link_once_the_last_stop_is_terminal(api):
    """PRD §3.7: "The driver's counters absorb the day: `drive_minutes_used_today` rises by
    `actual_drive_minutes`, and both `duty_minutes_used_today` and `weekly_on_duty_minutes` rise by
    `actual_duty_minutes`." And PRD §3.7: "The tractor's `odometer_miles` rises by the trip's
    `total_miles`, and its `miles_since_pm` is then recomputed as the new `odometer_miles` less
    `pm_last_service_odometer` — the second link caused by the first." And PRD §3.7: "Each
    `COMPLETED` `DELIVERY` stop's replenishment order moves `SCHEDULED → DELIVERED`, and each order
    that reaches `DELIVERED` lowers its store's `open_scheduled_cases` by that order's `cases` while
    raising the store's `delivered_cases_total` by the same amount."

    Design: Corner/cross_cutting_complexity_layers/a_refused_close_out_leaves_every_link_of_the_cascade_unapplied
    """
    ctx = _trip_with_one_stop_still_only_arrived()
    validate_error(
        api.complete_trip(ctx["trip"]["id"],
                          {"actual_drive_minutes": 160, "actual_duty_minutes": 255}, MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    finished = validate_success(api_client.complete_stop(ctx["stop_two"]["id"], {"cases_handled": 200}, ctx["crew"]))
    assert finished["status"] == "COMPLETED"

    closed = validate_success(
        api.complete_trip(ctx["trip"]["id"],
                          {"actual_drive_minutes": 160, "actual_duty_minutes": 255},
                          MANAGER)
    )
    assert closed["plan_status"] == "COMPLETED"
    assert closed["settlement_status"] == "ACCRUED"
    # 130 miles at 80 plus two paid stops at 2000 is 14400, lifted to the 20000 daily floor.
    assert closed["driver_pay_cents"] == 20000
    assert closed["delivered_cases"] == 600

    unit = read_tractor(ctx["tractor"]["id"])
    assert unit["odometer_miles"] == 50130
    assert unit["miles_since_pm"] == 10130
    assert unit["status"] == "AVAILABLE"
    ledger = read_store(ctx["store"]["id"])
    assert ledger["open_scheduled_cases"] == 0
    assert ledger["delivered_cases_total"] == 600
    crew_row = read_driver(ctx["driver"]["id"])
    assert crew_row["drive_minutes_used_today"] == 160
    assert crew_row["ytd_gross_cents"] == 20000


# --------------------------------------- deleting the middle stop re-derives everything ----


def _draft_trip_of_three_deliveries():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-C5")
    store = new_store(store_code="S-6250")
    orders = [new_order(store["id"], cases=cases, weight_lbs=cases * 22)
              for cases in (300, 600, 120)]
    trip = new_trip(domicile["id"], trip_code="TRIP-C5",
                    planned_start_at="2026-08-20T06:00:00Z")
    first = add_delivery_stop(trip["id"], store["id"], orders[0]["id"], 1,
                              "2026-08-20T08:00:00Z", "2026-08-20T08:45:00Z", 60, 50, 300)
    middle = add_delivery_stop(trip["id"], store["id"], orders[1]["id"], 2,
                               "2026-08-20T10:00:00Z", "2026-08-20T11:15:00Z", 60, 60, 600)
    last = add_delivery_stop(trip["id"], store["id"], orders[2]["id"], 3,
                             "2026-08-20T12:00:00Z", "2026-08-20T12:27:00Z", 30, 40, 120)
    assert first["service_minutes"] == 45
    assert middle["service_minutes"] == 75
    assert last["service_minutes"] == 27
    return {"store": store, "orders": orders, "trip": trip, "first": first,
            "middle": middle, "last": last}


def test_the_survivors_are_compacted_and_every_aggregate_is_recomputed(api):
    """PRD §3.4: "A planner may also remove a stop from a `DRAFT` trip. The surviving stops'
    `sequence` values are compacted so that the numbering remains contiguous from 1, every trip
    aggregate above is recomputed on the reduced stop set, and the trip's `version` advances." And
    PRD §3.4: "`planned_end_at` is the `scheduled_departure_at` of the highest-sequence stop, and
    it is null while the trip has no stops."

    Design: Corner/cross_cutting_complexity_layers/trip_aggregates_are_re_derived_after_a_middle_stop_is_deleted
    """
    ctx = _draft_trip_of_three_deliveries()
    full = read_trip(ctx["trip"]["id"], PLANNER)
    assert full["planned_service_minutes"] == 147
    assert full["planned_drive_minutes"] == 150
    assert full["planned_duty_minutes"] == 297
    assert full["total_miles"] == 150
    assert full["planned_delivery_cases"] == 1020
    assert full["stop_count"] == 3
    assert full["planned_end_at"] == "2026-08-20T12:27:00Z"

    reduced = validate_success(
        api.delete_trip_stop(ctx["trip"]["id"], ctx["middle"]["id"], PLANNER)
    )
    assert reduced["planned_service_minutes"] == 72
    assert reduced["planned_drive_minutes"] == 90
    assert reduced["planned_duty_minutes"] == 162
    assert reduced["total_miles"] == 90
    assert reduced["loaded_miles"] == 90
    assert reduced["empty_miles"] == 0
    assert reduced["planned_delivery_cases"] == 420
    assert reduced["stop_count"] == 2
    assert reduced["planned_end_at"] == "2026-08-20T12:27:00Z"

    survivor = validate_success(api.get_trip_stop(ctx["last"]["id"], PLANNER))
    assert survivor["sequence"] == 2
    assert survivor["scheduled_arrival_at"] == "2026-08-20T12:00:00Z"
    assert survivor["miles_from_prev"] == 40
    assert survivor["service_minutes"] == 27
    assert validate_success(api.get_trip_stop(ctx["first"]["id"], PLANNER))["sequence"] == 1

    # The trip is still DRAFT, so the deletion never reached the store ledger.
    assert read_store(ctx["store"]["id"])["open_scheduled_cases"] == 0
    assert validate_success(api.get_order(ctx["orders"][1]["id"], PLANNER))["status"] == "UNSCHEDULED"


def test_the_fuel_stop_appended_afterwards_carries_its_flat_twenty_five_minutes(api):
    """PRD §3.4: "For a `DROP_OFF` it is a flat twenty minutes, and for a `FUEL` stop a flat
    twenty-five minutes." And PRD §3.4: "`total_miles` sums `miles_from_prev` across all stops;
    `loaded_miles` sums `miles_from_prev` across only those stops whose `segment_loaded` is true;
    and `empty_miles` is total miles less loaded miles."

    Design: Corner/cross_cutting_complexity_layers/trip_aggregates_are_re_derived_after_a_middle_stop_is_deleted
    """
    ctx = _draft_trip_of_three_deliveries()
    validate_success(
        api.delete_trip_stop(ctx["trip"]["id"], ctx["middle"]["id"], PLANNER)
    )
    fuel = add_other_stop(ctx["trip"]["id"], "FUEL", 3, "2026-08-20T13:00:00Z",
                          "2026-08-20T13:20:00Z", 20, 10, segment_loaded=False)
    assert fuel["service_minutes"] == 25

    grown = read_trip(ctx["trip"]["id"], PLANNER)
    assert grown["planned_service_minutes"] == 97
    assert grown["planned_drive_minutes"] == 110
    assert grown["planned_duty_minutes"] == 207
    assert grown["total_miles"] == 100
    assert grown["loaded_miles"] == 90
    assert grown["empty_miles"] == 10
    assert grown["planned_delivery_cases"] == 420
    assert grown["stop_count"] == 3
    assert grown["planned_end_at"] == "2026-08-20T13:20:00Z"


# ---------------------------------- one scalar, two thresholds, two different owners ----


def _driver_thirty_four_points_down():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-C6")
    plan = new_pay_plan(plan_code="MILE-C")
    store = new_store(store_code="S-6260")
    driver = new_driver(domicile["id"], plan["id"], driver_code="D-C6")
    assert driver["safety_score"] == 100
    assert driver["coaching_hold"] is False
    tractor = new_tractor(domicile["id"], unit_code="TR-C6")
    trailer = new_trailer(domicile["id"], trailer_code="TL-C6")
    order = new_order(store["id"])
    trip = new_trip(domicile["id"], trip_code="TRIP-C6",
                    planned_start_at="2026-08-20T06:00:00Z")
    add_delivery_stop(trip["id"], store["id"], order["id"], 1, "2026-08-20T08:00:00Z",
                      "2026-08-20T09:15:00Z", 120, 100, 600)
    charged = [
        new_telematics_event(driver["id"], "SEATBELT", 3, "2026-07-10T14:00:00Z"),
        new_telematics_event(driver["id"], "HARD_BRAKE", 3, "2026-07-11T14:00:00Z"),
        new_telematics_event(driver["id"], "FOLLOWING_DISTANCE", 3, "2026-07-12T14:00:00Z"),
        new_telematics_event(driver["id"], "SPEEDING", 2, "2026-07-13T14:00:00Z"),
        new_telematics_event(driver["id"], "SEATBELT", 1, "2026-07-14T14:00:00Z"),
    ]
    assert charged[4]["penalty_points"] == 4
    return {"driver": driver, "tractor": tractor, "trailer": trailer, "trip": trip,
            "events": charged}


def _assign_the_held_driver(api, ctx):
    return api.assign_trip_resources(
        ctx["trip"]["id"],
        {"driver_id": ctx["driver"]["id"], "tractor_id": ctx["tractor"]["id"],
         "trailer_id": ctx["trailer"]["id"]},
        MANAGER,
    )


def test_a_score_of_exactly_seventy_swaps_the_hold_code_for_the_eligibility_code(api):
    """PRD §3.9: "`coaching_hold` is true exactly when `safety_score` is strictly below 70, which
    is to say when open points exceed thirty." And PRD §3.5: "**Driver eligibility** follows, in
    its own fixed internal order: a driver whose `coaching_hold` is true is refused with
    `ERR_DRIVER_COACHING_HOLD`; failing that, a driver whose `safety_score` is below 80 is refused
    with `ERR_DRIVER_SAFETY_INELIGIBLE`; failing that, the domicile comparison runs."

    Design: Corner/cross_cutting_complexity_layers/the_coaching_hold_arms_below_seventy_and_re_arms_when_new_points_land
    """
    ctx = _driver_thirty_four_points_down()
    held = read_driver(ctx["driver"]["id"], SAFETY)
    assert held["open_penalty_points"] == 34
    assert held["safety_score"] == 66
    assert held["coaching_hold"] is True
    validate_error(_assign_the_held_driver(api, ctx),
                   ApiErrorId.ERR_DRIVER_COACHING_HOLD, 422)

    coached = validate_success(
        api.coach_telematics_event(ctx["events"][4]["id"], {"coaching_note": "Belt reminder"},
                                   SAFETY)
    )
    assert coached["coached"] is True
    at_seventy = read_driver(ctx["driver"]["id"], SAFETY)
    assert at_seventy["open_penalty_points"] == 30
    assert at_seventy["safety_score"] == 70
    assert at_seventy["coaching_hold"] is False
    validate_error(_assign_the_held_driver(api, ctx),
                   ApiErrorId.ERR_DRIVER_SAFETY_INELIGIBLE, 422)


def test_one_two_point_event_re_arms_the_hold_that_coaching_had_just_cleared(api):
    """PRD §3.9: "The bases are 2 for `HARD_BRAKE`, 3 for `SPEEDING`, 2 for `FOLLOWING_DISTANCE`
    and 4 for `SEATBELT`, so a severity-3 seatbelt exception is worth twelve points while a
    severity-1 hard brake is worth two." And PRD §3.9: "Creating an event recomputes all three
    driver fields immediately, and if that recomputation flips `coaching_hold` from false to true,
    a cascade fires at once against everything the driver is currently holding."

    Design: Corner/cross_cutting_complexity_layers/the_coaching_hold_arms_below_seventy_and_re_arms_when_new_points_land
    """
    ctx = _driver_thirty_four_points_down()
    validate_success(
        api.coach_telematics_event(ctx["events"][4]["id"], {}, SAFETY)
    )
    re_armed_event = new_telematics_event(ctx["driver"]["id"], "FOLLOWING_DISTANCE", 1,
                                         "2026-07-30T14:00:00Z")
    assert re_armed_event["penalty_points"] == 2
    re_armed = read_driver(ctx["driver"]["id"], SAFETY)
    assert re_armed["open_penalty_points"] == 32
    assert re_armed["safety_score"] == 68
    assert re_armed["coaching_hold"] is True
    validate_error(_assign_the_held_driver(api, ctx),
                   ApiErrorId.ERR_DRIVER_COACHING_HOLD, 422)

    for event in ctx["events"][:4]:
        validate_success(api.coach_telematics_event(event["id"], {}, SAFETY))
    last = validate_success(api.coach_telematics_event(re_armed_event["id"], {}, SAFETY))
    assert last["coached"] is True
    restored = read_driver(ctx["driver"]["id"], SAFETY)
    assert restored["open_penalty_points"] == 0
    assert restored["safety_score"] == 100
    assert restored["coaching_hold"] is False

    crewed = validate_success(_assign_the_held_driver(api, ctx))
    assert crewed["driver_id"] == ctx["driver"]["id"]
