"""Inventory calculations (spoilage purge, FIFO by expiration, dispatch pre-kit)
and standalone business validations (slot config, discontinued product, suspended
host, overfill, auth-before-existence ordering).
"""
from test_helpers import validate_success, validate_error, api_client, counted_line
from test_helpers import (
    set_clock, make_host, make_product, make_machine, make_slot, make_driver,
    make_route, make_stop, dispatch, open_visit, reconcile, machine_version,
    MISSING_UUID,
)
from test_helpers.test_users import TEST_USERS, make_route_driver_headers

FIELD_OPS = TEST_USERS["field_ops_headers"]


# ─── Corner/calculations/spoilage_purge_sets_expired_lots_spoiled ──────────

def test_spoilage_purge_spoils_expired_lots():
    """PRD §3.3: "Every AVAILABLE lot whose expiration_date is at or before the
    current clock has its remaining_units set to 0 and its status set to SPOILED
    (the first cascade hop); the system then recomputes each affected slot's
    on_hand (the second cascade hop) and re-derives the machine's stock_status
    (the third cascade hop)."

    Design: Corner/calculations/spoilage_purge_sets_expired_lots_spoiled
    """
    set_clock("2026-06-01T00:00:00Z")
    host = make_host(name="Hs", contact_email="hs@x.com")
    prod = make_product(sku="SP", name="Sandwich", category="FRESH_FOOD",
                        unit_cost_cents=200, shelf_life_days=3)
    machine = make_machine(host["id"], asset_tag="SPT", machine_type="MICRO_MARKET_KIOSK")
    slot = make_slot(machine["id"], prod["id"], slot_code="SP1",
                     capacity=10, par_level=10, price_cents=500)
    driver = make_driver(full_name="Sp Drv", employee_code="EMPS")
    route = make_route(driver["id"], "2026-06-01T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 10)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])
    # Advance the clock past the lot's expiration (filled 06-01, shelf 3d -> exp 06-04).
    set_clock("2026-06-05T00:00:00Z")

    validate_success(api_client.spoilage_purge(machine["id"], FIELD_OPS), 200)
    slot_after = validate_success(api_client.get_slot(slot["id"], FIELD_OPS), 200)
    assert slot_after["on_hand"] == 0, slot_after
    lots = api_client.list_slot_lots(slot["id"], FIELD_OPS).json()["data"]
    assert len(lots) == 1, lots
    assert lots[0]["status"] == "SPOILED", lots[0]
    assert lots[0]["remaining_units"] == 0, lots[0]
    machine_after = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert machine_after["stock_status"] == "STOCKOUT", machine_after


# ─── Corner/calculations/fifo_oldest_expiration_consumed_first ─────────────

def test_fifo_draws_earlier_expiration_lot_first():
    """PRD §3.6: "The slot's AVAILABLE lots are ordered by expiration_date
    ascending with null expirations last, breaking ties by created_at ascending
    (never by id). Walking that order, the sale takes from each lot the smaller of
    the remaining quantity to fill and that lot's remaining_units".

    Two perishable lots: lot-A exp 2026-06-04 (6 units), lot-B exp 2026-06-07 (6
    units). A qty-8 sale draws 6 from A then 2 from B.

    Design: Corner/calculations/fifo_oldest_expiration_consumed_first
    """
    set_clock("2026-06-01T00:00:00Z")
    host = make_host(name="Hff", contact_email="hff@x.com")
    prod = make_product(sku="FF", name="Wrap", category="FRESH_FOOD",
                        unit_cost_cents=150, shelf_life_days=3)
    machine = make_machine(host["id"], asset_tag="FFT", machine_type="MICRO_MARKET_KIOSK")
    slot = make_slot(machine["id"], prod["id"], slot_code="FF1",
                     capacity=20, par_level=20, price_cents=400)
    driver = make_driver(full_name="Ff Drv", employee_code="EMPF")
    route = make_route(driver["id"], "2026-06-01T00:00:00Z")
    stop1 = make_stop(route["id"], machine["id"], 480, 540)
    dispatch(route["id"])
    v0 = machine["version"]
    # Lot A filled at clock 06-01 -> exp 06-04.
    visit1 = open_visit(stop1["id"], [counted_line(slot["id"], 0, 6)], v0, driver["id"])
    reconcile(visit1["id"], v0, driver["id"])
    v1 = machine_version(machine["id"])
    # Advance to 06-04, fill lot B -> exp 06-07.
    set_clock("2026-06-04T00:00:00Z")
    stop2 = make_stop(route["id"], machine["id"], 600, 660)
    visit2 = open_visit(stop2["id"], [counted_line(slot["id"], 6, 6)], v1, driver["id"])
    reconcile(visit2["id"], v1, driver["id"])

    # Identify the two lots by expiration.
    lots = api_client.list_slot_lots(slot["id"], FIELD_OPS).json()["data"]
    lot_a = min(lots, key=lambda l: l["expiration_date"])  # earlier expiration
    lot_b = max(lots, key=lambda l: l["expiration_date"])
    assert lot_a["expiration_date"] < lot_b["expiration_date"], lots

    sale = validate_success(api_client.create_sale(
        {"machine_id": machine["id"], "slot_id": slot["id"], "quantity": 8, "payment_method": "CASHLESS"},
        FIELD_OPS), 201)
    consumption = {e["lot_id"]: e["units"] for e in sale["lot_consumption_json"]}
    assert consumption.get(lot_a["id"]) == 6, consumption
    assert consumption.get(lot_b["id"]) == 2, consumption
    slot_after = validate_success(api_client.get_slot(slot["id"], FIELD_OPS), 200)
    assert slot_after["on_hand"] == 4, slot_after


# ─── Corner/calculations/prekit_computed_par_minus_onhand_at_dispatch ──────

def test_prekit_computed_at_dispatch():
    """PRD §3.4: "On dispatch, for each stop the system computes prekit_json as a
    map whose entries are, for each ACTIVE slot on the stop's machine, the slot
    identifier paired with the larger of zero and the difference between that
    slot's par_level and its current on_hand. Each stop then moves to KITTED".

    An empty slot (par 16, on_hand 0) yields a pre-kit of 16.

    Design: Corner/calculations/prekit_computed_par_minus_onhand_at_dispatch
    """
    host = make_host(name="Hpk", contact_email="hpk@x.com")
    prod = make_product(sku="PK", name="Pk", category="SNACK", unit_cost_cents=20)
    machine = make_machine(host["id"], asset_tag="PKT", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="PK1",
                     capacity=20, par_level=16, price_cents=100)
    driver = make_driver(full_name="Pk Drv", employee_code="EMPPK")
    route = make_route(driver["id"], "2026-06-28T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])

    validate_success(api_client.dispatch_route(route["id"], FIELD_OPS), 200)
    stop_after = validate_success(api_client.get_stop(stop["id"], FIELD_OPS), 200)
    assert stop_after["status"] == "KITTED", stop_after
    assert stop_after["prekit_json"].get(slot["id"]) == 16, stop_after


# ─── Corner/validations/slot_par_exceeds_capacity_returns_invalid_slot_config ─

def test_slot_par_exceeds_capacity_rejected():
    """PRD §3.3: "The slot's configuration is validated as a unit: par_level must
    not exceed capacity, capacity must be positive, price_cents must be positive,
    and slot_code must be unique within the machine; any violation is rejected with
    ERR_INVALID_SLOT_CONFIG (HTTP 422)."

    Design: Corner/validations/slot_par_exceeds_capacity_returns_invalid_slot_config
    """
    host = make_host(name="Hsc", contact_email="hsc@x.com")
    prod = make_product(sku="SC", name="Sc", category="SNACK", unit_cost_cents=20)
    machine = make_machine(host["id"], asset_tag="SCT", machine_type="SNACK_VENDOR")
    res = api_client.create_slot(
        machine["id"],
        {"product_id": prod["id"], "slot_code": "SC1", "capacity": 20, "par_level": 30, "price_cents": 100},
        FIELD_OPS)
    validate_error(res, "ERR_INVALID_SLOT_CONFIG", expected_status=422)


# ─── Corner/validations/add_discontinued_product_to_slot_rejected ──────────

def test_add_discontinued_product_to_slot_rejected():
    """PRD §3.1: "A DISCONTINUED product cannot be assigned to a new planogram
    slot; attempting to do so is rejected with ERR_PRODUCT_DISCONTINUED (HTTP
    409)."

    Design: Corner/validations/add_discontinued_product_to_slot_rejected
    """
    host = make_host(name="Hdc", contact_email="hdc@x.com")
    prod = make_product(sku="DC", name="Dc", category="SNACK", unit_cost_cents=20)
    validate_success(api_client.discontinue_product(prod["id"], FIELD_OPS), 200)
    machine = make_machine(host["id"], asset_tag="DCT", machine_type="SNACK_VENDOR")
    res = api_client.create_slot(
        machine["id"],
        {"product_id": prod["id"], "slot_code": "DC1", "capacity": 10, "par_level": 10, "price_cents": 100},
        FIELD_OPS)
    validate_error(res, "ERR_PRODUCT_DISCONTINUED", expected_status=409)


# ─── Corner/validations/place_machine_on_suspended_host_rejected ───────────

def test_place_machine_on_suspended_host_rejected():
    """PRD §3.1: "A SUSPENDED host blocks two operations: placing a new machine at
    that host, and opening a new commission statement for it. Both are rejected
    with ERR_HOST_SUSPENDED (HTTP 409)."

    Design: Corner/validations/place_machine_on_suspended_host_rejected
    """
    host = make_host(name="Hsu", contact_email="hsu@x.com")
    validate_success(api_client.suspend_host_site(host["id"], FIELD_OPS), 200)
    res = api_client.create_machine(
        {"host_site_id": host["id"], "asset_tag": "SUT", "machine_type": "SNACK_VENDOR"}, FIELD_OPS)
    validate_error(res, "ERR_HOST_SUSPENDED", expected_status=409)


# ─── Corner/validations/reconcile_overfill_line_returns_slot_overfill ──────

def test_reconcile_overfill_line_rejected():
    """PRD §3.5: "for each line, the sum of its refill_units and its physical_count
    to be no greater than the slot's capacity, or it is rejected with
    ERR_SLOT_OVERFILL (HTTP 422)."

    refill 5 + physical 8 = 13 > capacity 10.

    Design: Corner/validations/reconcile_overfill_line_returns_slot_overfill
    """
    set_clock("2026-06-29T00:00:00Z")
    host = make_host(name="Hof", contact_email="hof@x.com")
    prod = make_product(sku="OF", name="Of", category="SNACK", unit_cost_cents=20)
    machine = make_machine(host["id"], asset_tag="OFT", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="OF1",
                     capacity=10, par_level=10, price_cents=100)
    driver = make_driver(full_name="Of Drv", employee_code="EMPO")
    route = make_route(driver["id"], "2026-06-29T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 8, 5)], v0, driver["id"])
    res = api_client.reconcile_visit(
        visit["id"], {"expected_machine_version": v0}, make_route_driver_headers(driver["id"]))
    validate_error(res, "ERR_SLOT_OVERFILL", expected_status=422)


# ─── Corner/validations/priority_auth_before_existence ─────────────────────

def test_auth_outranks_existence():
    """PRD §2.9: "The order is: first, user-context presence and role validity
    (ERR_MISSING_OR_INVALID_USER_CONTEXT); ... third, existence of every
    path-referenced resource".
    PRD §2.1: "If either header is missing, or if X-User-Role carries a value that
    is not a recognized role, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT (HTTP 401)."

    A GET on a nonexistent machine with NO auth headers returns 401, not 404.

    Design: Corner/validations/priority_auth_before_existence
    """
    res = api_client.get_machine(MISSING_UUID, headers={})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT", expected_status=401)
