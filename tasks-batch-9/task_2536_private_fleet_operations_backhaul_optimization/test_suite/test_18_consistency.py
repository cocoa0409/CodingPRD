"""Consistency model: every cascade is already visible in the response that caused it."""

from test_helpers import (
    MAINTENANCE,
    MANAGER,
    PAYROLL,
    PLANNER,
    add_delivery_stop,
    api_client,
    assign_resources,
    make_driver_headers,
    new_domicile,
    new_driver,
    new_order,
    new_pay_plan,
    new_store,
    new_tractor,
    new_trailer,
    new_trip,
    read_store,
    read_tractor,
    read_trip,
    set_clock,
    validate_paginated,
    validate_success,
)


def _staffed_draft_trip_worth_ten_thousand():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-C7")
    plan = new_pay_plan(plan_code="MILE-Z", minimum_daily_cents=0)
    store = new_store(store_code="S-6270")
    driver = new_driver(domicile["id"], plan["id"], driver_code="D-C7")
    tractor = new_tractor(domicile["id"], unit_code="TR-C7")
    trailer = new_trailer(domicile["id"], trailer_code="TL-C7")
    order = new_order(store["id"])
    trip = new_trip(domicile["id"], trip_code="TRIP-C7",
                    planned_start_at="2026-08-20T06:00:00Z")
    stop = add_delivery_stop(trip["id"], store["id"], order["id"], 1, "2026-08-20T08:00:00Z",
                            "2026-08-20T09:15:00Z", 120, 100, 600)
    # The append's own response already carries the derived service time.
    assert stop["service_minutes"] == 75
    aggregated = read_trip(trip["id"], PLANNER)
    assert aggregated["planned_duty_minutes"] == 195
    assert aggregated["total_miles"] == 100
    assign_resources(trip["id"], driver["id"], tractor["id"], trailer["id"])
    return {"domicile": domicile, "plan": plan, "store": store, "driver": driver,
            "tractor": tractor, "order": order, "trip": trip, "stop": stop,
            "crew": make_driver_headers(driver["id"])}


def test_the_commit_response_carries_the_pin_the_price_and_the_scheduled_ledger(api):
    """PRD §2.10: "Cascades in this system are chains, not single steps, and each link in a chain
    is a real mutation of a real row with its own `version` and `updated_at` movement." And PRD
    §3.5: "The **pay-plan pin** is taken: `pinned_pay_plan_id` becomes the assigned driver's
    current `pay_plan_id`, and `pinned_pay_plan_version` becomes that plan's `version` as observed
    at this instant." And PRD §3.5: "Every `DELIVERY` stop's order moves `UNSCHEDULED →
    SCHEDULED`, and each order that turned `SCHEDULED` raises its store's `open_scheduled_cases`
    by that order's `cases` — a two-link chain in which the ledger movement is caused by the order
    transition, not by the commitment call itself."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_body_of_the_call_that_caused_it
    """
    ctx = _staffed_draft_trip_worth_ten_thousand()
    committed = validate_success(api.plan_trip(ctx["trip"]["id"], PLANNER))
    assert committed["plan_status"] == "PLANNED"
    assert committed["planned_pay_cents"] == 10000
    assert committed["pinned_pay_plan_id"] == ctx["plan"]["id"]
    assert committed["pinned_pay_plan_version"] == ctx["plan"]["version"]

    # The very first read after that call already shows both links of the chain.
    assert validate_success(api.get_order(ctx["order"]["id"], PLANNER))["status"] == "SCHEDULED"
    assert read_store(ctx["store"]["id"])["open_scheduled_cases"] == 600

    dispatched = validate_success(api.dispatch_trip(ctx["trip"]["id"], MANAGER))
    assert dispatched["plan_status"] == "DISPATCHED"
    arrived = validate_success(api_client.arrive_at_stop(ctx["stop"]["id"], ctx["crew"]))
    assert arrived["status"] == "ARRIVED"
    # The parent's bubble-up is observable immediately after the child's transition.
    assert read_trip(ctx["trip"]["id"])["plan_status"] == "IN_PROGRESS"


def test_the_close_out_response_and_the_first_follow_up_reads_agree_exactly(api):
    """PRD §3.8: "The created statement then raises the driver's domicile `accrued_pay_cents` by
    `gross_cents` and the driver's own `ytd_gross_cents` by `gross_cents` — a second link caused by
    the statement's creation." And PRD §3.7: "`delivered_cases` is set to the sum of `cases` over
    the trip's `DELIVERY` stops whose own status is `COMPLETED`." And PRD §2.4: "Reads never move a
    version."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_body_of_the_call_that_caused_it
    """
    ctx = _staffed_draft_trip_worth_ten_thousand()
    validate_success(api.plan_trip(ctx["trip"]["id"], PLANNER))
    validate_success(api.dispatch_trip(ctx["trip"]["id"], MANAGER))
    validate_success(api_client.arrive_at_stop(ctx["stop"]["id"], ctx["crew"]))
    finished = validate_success(
        api_client.complete_stop(ctx["stop"]["id"], {"cases_handled": 600}, ctx["crew"])
    )
    assert finished["status"] == "COMPLETED"

    closed = validate_success(
        api.complete_trip(ctx["trip"]["id"],
                          {"actual_drive_minutes": 120, "actual_duty_minutes": 195},
                          MANAGER)
    )
    assert closed["plan_status"] == "COMPLETED"
    assert closed["settlement_status"] == "ACCRUED"
    assert closed["driver_pay_cents"] == 10000
    assert closed["delivered_cases"] == 600

    rows, meta = validate_paginated(
        api.list_pay_statements(PAYROLL, {"trip_id": ctx["trip"]["id"], "limit": 10,
                                          "offset": 0})
    )
    assert meta["total_count"] == 1
    assert rows[0]["gross_cents"] == closed["driver_pay_cents"]
    assert rows[0]["status"] == "ACCRUED"
    assert rows[0]["variant"] == "FINAL_SETTLEMENT"

    unit = read_tractor(ctx["tractor"]["id"], MAINTENANCE)
    assert unit["odometer_miles"] == 50100
    assert unit["miles_since_pm"] == 10100
    assert unit["status"] == "AVAILABLE"

    crew_row = validate_success(api.get_driver(ctx["driver"]["id"], PAYROLL))
    assert crew_row["ytd_gross_cents"] == 10000
    assert crew_row["duty_minutes_used_today"] == 195
    assert validate_success(api.get_domicile(ctx["domicile"]["id"], PAYROLL))["accrued_pay_cents"] == 10000

    assert validate_success(api.get_order(ctx["order"]["id"], PLANNER))["status"] == "DELIVERED"
    ledger = read_store(ctx["store"]["id"])
    assert ledger["open_scheduled_cases"] == 0
    assert ledger["delivered_cases_total"] == 600
