"""Order booking/settlement state machines, the delivery-run cycle, and the
multi-hop cascades that confirm/cancel/return trigger.

Difficulty: parallel booking x settlement dimensions, the cyclic DeliveryRun
loop, the confirm->hold->ledger depth-2 chain, and the cancel->release->credit
depth-3 chain. Corner: a clean SUCCESS completion and the cancel cascade that
releases lines and cancels runs in one request, plus immediate-consistency of
confirm totals.
"""
from test_helpers import (
    validate_success,
    api_client,
    make_customer_headers,
    TEST_USERS,
    create_catalog_item_payload,
    create_customer_payload,
    create_venue_payload,
    create_order_payload,
    add_line_payload,
    create_crew_payload,
    create_delivery_run_payload,
    get_success_data,
)

AGENT = TEST_USERS["rental_agent_headers"]


def _item(**ov):
    return get_success_data(api_client.create_catalog_item(create_catalog_item_payload(**ov), AGENT))


def _customer():
    return get_success_data(api_client.create_customer(create_customer_payload(), AGENT))


def _will_call(customer_id, **ov):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order(create_order_payload(customer_id, **ov), h))


def _delivery(customer_id, venue_id, **ov):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, fulfillment="DELIVERY", venue_id=venue_id, **ov), h))


def _venue(customer_id, zone="LOCAL"):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_venue(
        create_venue_payload(customer_id, delivery_zone=zone), h))


def _add_line(order_id, item_id, qty, customer_id):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.add_line(order_id, add_line_payload(item_id, qty), h))


def _confirm(order_id, customer_id):
    h = make_customer_headers(customer_id)
    cur = get_success_data(api_client.get_order(order_id, h))
    return validate_success(
        api_client.confirm_order(order_id, {"expected_order_version": cur["version"]}, h), 200)


def _crew(**ov):
    return get_success_data(api_client.create_crew(create_crew_payload(**ov), AGENT))


def _run(order_id, crew_id, leg, ws, we):
    return get_success_data(api_client.create_delivery_run(
        create_delivery_run_payload(order_id, crew_id, leg=leg, window_start=ws, window_end=we), AGENT))


# ─── Difficulty: parallel booking x settlement dimensions ───

def test_booking_advances_while_settlement_holds(api):
    """PRD §2.6: "A `RentalOrder` is governed by two parallel, independent status
    fields that evolve on different triggers and must be tracked separately."
    PRD §3.5: "When the goods come back, the rental agent returns the order,
    advancing `booking_status` `FULFILLED → RETURNED`."

    Confirm holds the deposit (settlement_status=DEPOSIT_HELD); fulfill then
    return drive booking_status to RETURNED, but settlement_status stays
    DEPOSIT_HELD because no settle action has run.

    Design: Difficulty/non_linear_state_machine/rental_order_parallel_booking_and_settlement_dimensions
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=100, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], event_start="2026-06-10T00:00:00.000Z",
                       event_end="2026-06-10T00:00:00.000Z")
    _add_line(order["id"], item["id"], 10, cust["id"])
    confirmed = _confirm(order["id"], cust["id"])
    assert confirmed["booking_status"] == "CONFIRMED"
    assert confirmed["settlement_status"] == "DEPOSIT_HELD"

    get_success_data(api_client.fulfill_order(order["id"], AGENT))
    returned = validate_success(api_client.return_order(order["id"], AGENT), 200)
    assert returned["booking_status"] == "RETURNED", returned["booking_status"]
    assert returned["settlement_status"] == "DEPOSIT_HELD", returned["settlement_status"]


def test_delivery_run_failed_then_reschedule_cycles_back(api):
    """PRD §3.6: "Reporting `FAILED` advances a scheduled run `SCHEDULED →
    ATTEMPTED` and increments its `attempt_count` by one."
    PRD §3.6: "An attempted run can be rescheduled back to a fresh window,
    advancing `status` `ATTEMPTED → SCHEDULED` and updating its `window_start` and
    `window_end`."

    A run fails (ATTEMPTED, attempt_count=1) then reschedules back to SCHEDULED;
    attempt_count remains 1 (reschedule does not increment it).

    Design: Difficulty/non_linear_state_machine/delivery_run_cyclic_scheduled_attempted_loop
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    venue = _venue(cust["id"])
    order = _delivery(cust["id"], venue["id"], event_start="2026-07-01T00:00:00.000Z",
                      event_end="2026-07-01T00:00:00.000Z")
    _add_line(order["id"], item["id"], 1, cust["id"])
    _confirm(order["id"], cust["id"])
    crew = _crew(name="Truck 1", turnaround_minutes=0)
    run = _run(order["id"], crew["id"], "DROP_OFF",
               "2026-06-30T09:00:00.000Z", "2026-06-30T10:00:00.000Z")
    get_success_data(api_client.attempt_delivery_run(run["id"], {"outcome": "FAILED"}, AGENT))
    rescheduled = validate_success(api_client.reschedule_delivery_run(
        run["id"], {"window_start": "2026-06-30T13:00:00.000Z",
                    "window_end": "2026-06-30T14:00:00.000Z"}, AGENT), 200)
    assert rescheduled["status"] == "SCHEDULED", rescheduled["status"]
    assert rescheduled["attempt_count"] == 1, rescheduled["attempt_count"]


# ─── Difficulty: transitive cascades ───

def test_confirm_holds_deposit_and_appends_hold_ledger(api):
    """PRD §3.4: "As a cross-dimension cascade, the settlement side advances
    `settlement_status` `UNSETTLED → DEPOSIT_HELD` and the system appends a deposit
    ledger entry of kind `HOLD` whose `amount_cents` equals the order's
    `deposit_total_cents`."

    Confirm (5 chairs, deposit 300 each) => settlement_status DEPOSIT_HELD,
    deposit_total 1500, exactly one HOLD ledger entry of 1500.

    Design: Difficulty/transitive_cascade/order_confirm_holds_deposit_appends_ledger_depth2
    """
    item = _item(category="CHAIR", total_units=50, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=300, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], event_start="2026-06-16T00:00:00.000Z",
                       event_end="2026-06-16T00:00:00.000Z")
    _add_line(order["id"], item["id"], 5, cust["id"])
    confirmed = _confirm(order["id"], cust["id"])
    assert confirmed["settlement_status"] == "DEPOSIT_HELD"
    assert confirmed["deposit_total_cents"] == 1500, confirmed["deposit_total_cents"]

    entries = validate_success(api_client.get_deposit_ledger(order["id"], AGENT), 200)
    assert len(entries) == 1, f"expected exactly one ledger entry, got {len(entries)}"
    assert entries[0]["kind"] == "HOLD", entries[0]["kind"]
    assert entries[0]["amount_cents"] == 1500, entries[0]["amount_cents"]


def test_cancel_releases_deposit_and_credits_customer(api):
    """PRD §3.5: "if the order's `settlement_status` is `DEPOSIT_HELD` at the time
    of cancellation, the settlement dimension advances `DEPOSIT_HELD →
    DEPOSIT_RELEASED`, the system appends a deposit ledger entry of kind `RELEASE`
    for the current held balance, and the owning customer's `account_credit_cents`
    is recomputed to reflect that release."

    Depth-3 cascade: cancel -> DEPOSIT_RELEASED -> customer credited 1500.

    Design: Difficulty/transitive_cascade/order_cancel_releases_deposit_credits_customer_depth3
    """
    item = _item(category="CHAIR", total_units=50, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=300, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], event_start="2026-06-15T00:00:00.000Z",
                       event_end="2026-06-15T00:00:00.000Z")
    _add_line(order["id"], item["id"], 5, cust["id"])
    confirmed = _confirm(order["id"], cust["id"])
    h = make_customer_headers(cust["id"])
    cancelled = validate_success(api_client.cancel_order(
        order["id"], {"expected_order_version": confirmed["version"]}, h), 200)
    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["settlement_status"] == "DEPOSIT_RELEASED"

    customer = validate_success(api_client.get_customer(cust["id"], AGENT), 200)
    assert customer["account_credit_cents"] == 1500, customer["account_credit_cents"]


# ─── Corner: valid completion + cascade + consistency ───

def test_delivery_run_success_completes(api):
    """PRD §3.6: "Reporting `SUCCESS` advances a scheduled run `SCHEDULED →
    COMPLETED`; a successful drop-off run is what unblocks the order's
    fulfillment, and a successful pickup run is what unblocks the order's return."

    Design: Corner/state_machines/delivery_run_success_completes
    """
    item = _item(category="CHAIR", total_units=10, daily_rate_cents=200,
                 deposit_per_unit_cents=0)
    cust = _customer()
    venue = _venue(cust["id"])
    order = _delivery(cust["id"], venue["id"], event_start="2026-07-22T00:00:00.000Z",
                      event_end="2026-07-22T00:00:00.000Z")
    _add_line(order["id"], item["id"], 1, cust["id"])
    _confirm(order["id"], cust["id"])
    crew = _crew(name="Truck 26", turnaround_minutes=0)
    run = _run(order["id"], crew["id"], "DROP_OFF",
               "2026-07-22T08:00:00.000Z", "2026-07-22T09:00:00.000Z")
    completed = validate_success(
        api_client.attempt_delivery_run(run["id"], {"outcome": "SUCCESS"}, AGENT), 200)
    assert completed["status"] == "COMPLETED", completed["status"]


def test_cancel_cascades_release_lines_and_cancel_runs(api):
    """PRD §3.5: "Every line not already `RELEASED` has its `status` set to
    `RELEASED`, freeing its inventory window. Every delivery run for the order that
    is `SCHEDULED` or `ATTEMPTED` has its `status` set to `CANCELLED`."

    Design: Corner/cross_cutting_complexity_layers/cancel_cascades_release_lines_and_runs
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 deposit_per_unit_cents=0)
    cust = _customer()
    venue = _venue(cust["id"])
    order = _delivery(cust["id"], venue["id"], event_start="2026-07-28T00:00:00.000Z",
                      event_end="2026-07-28T00:00:00.000Z")
    _add_line(order["id"], item["id"], 1, cust["id"])
    confirmed = _confirm(order["id"], cust["id"])
    crew = _crew(name="Truck 47", turnaround_minutes=0)
    run = _run(order["id"], crew["id"], "DROP_OFF",
               "2026-07-28T08:00:00.000Z", "2026-07-28T09:00:00.000Z")
    h = make_customer_headers(cust["id"])
    cancelled = validate_success(api_client.cancel_order(
        order["id"], {"expected_order_version": confirmed["version"]}, h), 200)
    assert cancelled["booking_status"] == "CANCELLED"
    run_after = validate_success(api_client.get_delivery_run(run["id"], AGENT), 200)
    assert run_after["status"] == "CANCELLED", run_after["status"]


def test_confirm_totals_present_in_same_response(api):
    """PRD §3.4: "The system then recomputes and records `rental_subtotal_cents`,
    `delivery_fee_cents`, `cleaning_fee_total_cents`, `deposit_total_cents`, and
    `grand_total_cents` using the pricing rules of §3.3."

    5 chairs, daily 200, 1 day, deposit 100 each: rental_subtotal 1000,
    deposit_total 500, grand_total 1000 — all present on the confirm response.

    Design: Corner/consistency_model/confirm_totals_visible_in_same_response
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=100, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], event_start="2026-06-01T00:00:00.000Z",
                       event_end="2026-06-01T00:00:00.000Z")
    _add_line(order["id"], item["id"], 5, cust["id"])
    confirmed = _confirm(order["id"], cust["id"])
    assert confirmed["rental_subtotal_cents"] == 1000, confirmed["rental_subtotal_cents"]
    assert confirmed["deposit_total_cents"] == 500, confirmed["deposit_total_cents"]
    assert confirmed["grand_total_cents"] == 1000, confirmed["grand_total_cents"]
