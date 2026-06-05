"""Inventory availability over overlapping windows, crew-window discipline, and
the reserve/release conservation invariants.

Difficulty: aggregate-capacity boundary on confirm, closed-interval inventory
overlap, half-open crew window + turnaround buffer, deposit-balance conservation,
inventory-unit conservation. Corner: availability read reflecting reserved units.
"""
from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    make_customer_headers,
    TEST_USERS,
    ApiErrorId,
    compute_held_balance,
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


def _will_call(customer_id, ws, we):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, event_start=ws, event_end=we), h))


def _delivery(customer_id, venue_id, ws, we):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, fulfillment="DELIVERY", venue_id=venue_id,
                             event_start=ws, event_end=we), h))


def _venue(customer_id, zone="LOCAL"):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.create_venue(
        create_venue_payload(customer_id, delivery_zone=zone), h))


def _add_line(order_id, item_id, qty, customer_id):
    h = make_customer_headers(customer_id)
    return get_success_data(api_client.add_line(order_id, add_line_payload(item_id, qty), h))


def _confirm_ok(order_id, customer_id):
    h = make_customer_headers(customer_id)
    cur = get_success_data(api_client.get_order(order_id, h))
    return validate_success(
        api_client.confirm_order(order_id, {"expected_order_version": cur["version"]}, h), 200)


def _confirm_raw(order_id, customer_id):
    h = make_customer_headers(customer_id)
    cur = get_success_data(api_client.get_order(order_id, h))
    return api_client.confirm_order(order_id, {"expected_order_version": cur["version"]}, h)


def _crew(**ov):
    return get_success_data(api_client.create_crew(create_crew_payload(**ov), AGENT))


# ─── Difficulty: inventory capacity boundary on confirm ───

def test_inventory_capacity_exact_cutover_rejects_overflow(api):
    """PRD §3.4: "the units already reserved on overlapping windows plus this
    line's `quantity` must not exceed the item's `total_units`, and a shortfall is
    rejected with `ERR_INVENTORY_UNAVAILABLE`."

    total_units=100; OA reserves 60 over Jun1-3; OB requests 41 over Jun3-5
    (overlaps Jun3): 60+41=101 > 100 => ERR_INVENTORY_UNAVAILABLE.

    Design: Difficulty/boundary_precision_check/inventory_capacity_exact_boundary_on_confirm
    """
    item = _item(category="CHAIR", total_units=100, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    oa = _will_call(cust["id"], "2026-06-01T00:00:00.000Z", "2026-06-03T00:00:00.000Z")
    _add_line(oa["id"], item["id"], 60, cust["id"])
    _confirm_ok(oa["id"], cust["id"])

    ob = _will_call(cust["id"], "2026-06-03T00:00:00.000Z", "2026-06-05T00:00:00.000Z")
    _add_line(ob["id"], item["id"], 41, cust["id"])
    resp = _confirm_raw(ob["id"], cust["id"])
    validate_error(resp, ApiErrorId.ERR_INVENTORY_UNAVAILABLE.value, 409)


def test_inventory_closed_interval_overlap_aggregates_quantities(api):
    """PRD §2.7: "Two day-spans overlap when each begins on or before the other
    ends; a reservation that ends on the very day another begins is treated as
    overlapping, since both occupy that shared day."
    PRD §3.4: "the units already reserved on overlapping windows plus this line's
    `quantity` must not exceed the item's `total_units`, and a shortfall is
    rejected with `ERR_INVENTORY_UNAVAILABLE`."

    total_units=100; OD1 reserves 80 Jun1-3; OD2 requests 30 Jun3-5 (share Jun3):
    80+30=110 > 100 => ERR_INVENTORY_UNAVAILABLE.

    Design: Difficulty/resource_temporal_overlap/inventory_closed_interval_aggregate_capacity_overlap
    """
    item = _item(category="CHAIR", total_units=100, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    od1 = _will_call(cust["id"], "2026-06-01T00:00:00.000Z", "2026-06-03T00:00:00.000Z")
    _add_line(od1["id"], item["id"], 80, cust["id"])
    _confirm_ok(od1["id"], cust["id"])

    od2 = _will_call(cust["id"], "2026-06-03T00:00:00.000Z", "2026-06-05T00:00:00.000Z")
    _add_line(od2["id"], item["id"], 30, cust["id"])
    resp = _confirm_raw(od2["id"], cust["id"])
    validate_error(resp, ApiErrorId.ERR_INVENTORY_UNAVAILABLE.value, 409)


# ─── Difficulty: crew window + turnaround buffer ───

def test_crew_window_conflict_within_turnaround_buffer(api):
    """PRD §2.8: "a collision means the two windows overlap or are separated by
    less than the crew's turnaround buffer."
    PRD §3.6: "the system rejects the new window if it collides with any other
    non-`CANCELLED` run on the same crew once the crew's `turnaround_minutes`
    buffer is taken into account — two windows conflict if they overlap or sit
    closer together than the buffer allows — returning `ERR_CREW_WINDOW_CONFLICT`."

    turnaround=60; first run [09:00,10:00); second [10:30,11:30) is only 30 min
    after the first closes, less than the 60-min buffer => ERR_CREW_WINDOW_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/crew_half_open_plus_turnaround_buffer_overlap
    """
    item = _item(category="CHAIR", total_units=50, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    venue = _venue(cust["id"])
    oa = _delivery(cust["id"], venue["id"], "2026-07-10T00:00:00.000Z", "2026-07-10T00:00:00.000Z")
    _add_line(oa["id"], item["id"], 1, cust["id"])
    _confirm_ok(oa["id"], cust["id"])
    ob = _delivery(cust["id"], venue["id"], "2026-07-10T00:00:00.000Z", "2026-07-10T00:00:00.000Z")
    _add_line(ob["id"], item["id"], 1, cust["id"])
    _confirm_ok(ob["id"], cust["id"])
    crew = _crew(name="Truck 16", turnaround_minutes=60)
    get_success_data(api_client.create_delivery_run(
        create_delivery_run_payload(oa["id"], crew["id"], leg="DROP_OFF",
                                    window_start="2026-07-10T09:00:00.000Z",
                                    window_end="2026-07-10T10:00:00.000Z"), AGENT))
    resp = api_client.create_delivery_run(
        create_delivery_run_payload(ob["id"], crew["id"], leg="DROP_OFF",
                                    window_start="2026-07-10T10:30:00.000Z",
                                    window_end="2026-07-10T11:30:00.000Z"), AGENT)
    validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT.value, 409)


# ─── Difficulty: conservation invariants ───

def test_deposit_hold_then_release_conserves_balance_to_zero(api):
    """PRD §3.7: "The current held-deposit balance of an order is derived by
    replaying its ledger entries in `created_at` ascending order, starting from
    zero, adding each `HOLD` entry's `amount_cents` and subtracting each `RELEASE`
    and each `FORFEIT` entry's `amount_cents`."

    Confirm holds 1000; cancel releases 1000; the ledger replays to a held
    balance of 0 (one HOLD 1000, one RELEASE 1000), customer credited 1000.

    Design: Difficulty/compensating_invariant/deposit_ledger_hold_then_release_conserves_balance
    """
    item = _item(category="CHAIR", total_units=20, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=200, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], "2026-06-25T00:00:00.000Z", "2026-06-25T00:00:00.000Z")
    _add_line(order["id"], item["id"], 5, cust["id"])
    confirmed = _confirm_ok(order["id"], cust["id"])
    h = make_customer_headers(cust["id"])
    released = validate_success(api_client.cancel_order(
        order["id"], {"expected_order_version": confirmed["version"]}, h), 200)
    assert released["settlement_status"] == "DEPOSIT_RELEASED"

    customer = validate_success(api_client.get_customer(cust["id"], AGENT), 200)
    assert customer["account_credit_cents"] == 1000, customer["account_credit_cents"]

    entries = validate_success(api_client.get_deposit_ledger(order["id"], AGENT), 200)
    holds = [e for e in entries if e["kind"] == "HOLD"]
    releases = [e for e in entries if e["kind"] == "RELEASE"]
    assert len(holds) == 1 and holds[0]["amount_cents"] == 1000
    assert len(releases) == 1 and releases[0]["amount_cents"] == 1000
    assert compute_held_balance(entries) == 0


def test_inventory_reserve_then_release_restores_availability(api):
    """PRD §2.7: "Availability over a queried window is the item's `total_units`
    minus the number of units already reserved on lines whose reserved window
    overlaps the queried window."
    PRD §3.5: "Cancellation drives a multi-hop cascade. Every line not already
    `RELEASED` has its `status` set to `RELEASED`, freeing its inventory window."

    Confirm reserves all 40 units over Jun1-2; cancel releases them; availability
    over Jun1-2 returns to 40 with 0 reserved.

    Design: Difficulty/compensating_invariant/inventory_units_reserve_then_release_conserves_availability
    """
    item = _item(category="CHAIR", total_units=40, daily_rate_cents=200,
                 multi_day_discount_pct=0, deposit_per_unit_cents=0, requires_coi=False)
    cust = _customer()
    order = _will_call(cust["id"], "2026-06-01T00:00:00.000Z", "2026-06-02T00:00:00.000Z")
    _add_line(order["id"], item["id"], 40, cust["id"])
    confirmed = _confirm_ok(order["id"], cust["id"])
    h = make_customer_headers(cust["id"])
    cancelled = validate_success(api_client.cancel_order(
        order["id"], {"expected_order_version": confirmed["version"]}, h), 200)
    assert cancelled["booking_status"] == "CANCELLED"

    avail = validate_success(api_client.get_item_availability(
        item["id"], "2026-06-01T00:00:00.000Z", "2026-06-02T00:00:00.000Z", AGENT), 200)
    assert avail["available_units"] == 40, avail["available_units"]
    assert avail["reserved_units"] == 0, avail["reserved_units"]


# ─── Corner: availability read ───

def test_availability_reflects_reserved_units(api):
    """PRD §2.7: "An availability read takes the queried `window_start` and
    `window_end` and reports, for the item identified by `item_id`, the
    `total_units` the yard owns, the `reserved_units` already committed over the
    overlapping window, and the resulting `available_units` (the total minus the
    reserved)."

    total_units=50, 30 reserved over Jun1-2: reserved_units=30, available_units=20.

    Design: Corner/endpoints/availability_reflects_reserved_units
    """
    item = _item(category="CHAIR", total_units=50, daily_rate_cents=200,
                 deposit_per_unit_cents=0)
    cust = _customer()
    order = _will_call(cust["id"], "2026-06-01T00:00:00.000Z", "2026-06-02T00:00:00.000Z")
    _add_line(order["id"], item["id"], 30, cust["id"])
    _confirm_ok(order["id"], cust["id"])
    avail = validate_success(api_client.get_item_availability(
        item["id"], "2026-06-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z", AGENT), 200)
    assert avail["reserved_units"] == 30, avail["reserved_units"]
    assert avail["available_units"] == 20, avail["available_units"]
