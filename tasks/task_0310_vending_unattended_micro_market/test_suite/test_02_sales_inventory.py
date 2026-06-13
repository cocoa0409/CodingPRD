"""Sales: provisional vs final-FIFO COGS, FIFO lot consumption, insufficient
stock boundary, and the compensating void reversal that conserves both physical
inventory and vault cash.
"""
from test_helpers import validate_success, validate_error, api_client, counted_line
from test_helpers import (
    set_clock, make_host, make_product, make_machine, make_slot, make_driver,
    make_route, make_stop, dispatch, open_visit, reconcile, make_sale,
    machine_version,
)
from test_helpers.test_users import TEST_USERS

FIELD_OPS = TEST_USERS["field_ops_headers"]


# ─── dual_variant_calc / dvc_provisional_vs_final_fifo_cogs_on_sale ────────

def _slot_with_two_cost_lots():
    """Slot holding 12 units @ 40c (older) + 8 units @ 90c, weighted avg 60c.
    Returns (machine, slot)."""
    set_clock("2026-06-01T00:00:00Z")
    host = make_host(name="Lobby A", contact_email="a@x.com")
    prod = make_product(sku="CHIP40", name="Chips", category="SNACK", unit_cost_cents=40)
    machine = make_machine(host["id"], asset_tag="M-1", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="A1",
                     capacity=30, par_level=30, price_cents=150)
    driver = make_driver(full_name="Dee Driver", employee_code="EMP1")
    route = make_route(driver["id"], "2026-06-01T00:00:00Z")
    stop1 = make_stop(route["id"], machine["id"], 480, 540)
    dispatch(route["id"])
    v0 = machine["version"]
    visit1 = open_visit(stop1["id"], [counted_line(slot["id"], 0, 12)], v0, driver["id"])
    reconcile(visit1["id"], v0, driver["id"])
    v1 = machine_version(machine["id"])
    # Re-price the product to 90c; only lots filled afterwards snapshot the new cost.
    validate_success(api_client.update_product_cost(prod["id"], {"unit_cost_cents": 90}, FIELD_OPS), 200)
    stop2 = make_stop(route["id"], machine["id"], 600, 660)
    visit2 = open_visit(stop2["id"], [counted_line(slot["id"], 12, 8)], v1, driver["id"])
    reconcile(visit2["id"], v1, driver["id"])
    return machine, slot


def test_provisional_cogs_uses_weighted_average_cost():
    """PRD §3.6: "It computes the read-only provisional_cogs_cents using a slot
    weighted-average cost taken over the slot's AVAILABLE lots before this sale
    draws anything down: the average cost is the sum, over those available lots,
    of each lot's remaining_units multiplied by its own snapshot unit_cost_cents,
    divided by the sum of remaining_units across those lots, with that average
    rounded half-up to whole cents; the provisional cost of goods is then that
    rounded average multiplied by quantity."

    Design: Difficulty/dual_variant_calc/dvc_provisional_vs_final_fifo_cogs_on_sale
    """
    machine, slot = _slot_with_two_cost_lots()
    # avg = (12*40 + 8*90)/20 = 1200/20 = 60c; provisional = 60 * 5 = 300.
    sale = validate_success(api_client.create_sale(
        {"machine_id": machine["id"], "slot_id": slot["id"], "quantity": 5, "payment_method": "CASHLESS"},
        FIELD_OPS), 201)
    assert sale["provisional_cogs_cents"] == 300, sale
    assert sale["gross_cents"] == 750, sale


def test_fifo_consumes_oldest_cost_lot_first():
    """PRD §3.6: "Walking that order, the sale takes from each lot the smaller of
    the remaining quantity to fill and that lot's remaining_units, decrements the
    lot's remaining_units by the amount taken, marks the lot DEPLETED when its
    remaining_units reaches zero, and appends a record of the lot identifier and
    units taken to the sale's read-only lot_consumption_json".
    PRD §3.6: "The slot's AVAILABLE lots are ordered by expiration_date ascending
    with null expirations last, breaking ties by created_at ascending (never by
    id)."

    The qty-5 sale draws entirely from the older 40c lot (12 units, created
    first), so the realized FIFO cost is 5*40 = 200, distinct from the provisional
    weighted-average figure of 300.

    Design: Difficulty/dual_variant_calc/dvc_provisional_vs_final_fifo_cogs_on_sale
    """
    machine, slot = _slot_with_two_cost_lots()
    # Identify the older (40c) lot.
    lots, _ = _list_slot_lots(slot["id"])
    lots_sorted = sorted(lots, key=lambda l: l["created_at"])
    older_lot = lots_sorted[0]
    assert older_lot["unit_cost_cents"] == 40, older_lot

    sale = validate_success(api_client.create_sale(
        {"machine_id": machine["id"], "slot_id": slot["id"], "quantity": 5, "payment_method": "CASHLESS"},
        FIELD_OPS), 201)
    consumption = sale["lot_consumption_json"]
    total_drawn = sum(entry["units"] for entry in consumption)
    assert total_drawn == 5, consumption
    # All 5 units come from the oldest (40c) lot.
    drawn_from_older = sum(e["units"] for e in consumption if e["lot_id"] == older_lot["id"])
    assert drawn_from_older == 5, consumption
    realized_cost = sum(e["units"] * 40 for e in consumption if e["lot_id"] == older_lot["id"])
    assert realized_cost == 200, consumption


def _list_slot_lots(slot_id):
    body = api_client.list_slot_lots(slot_id, FIELD_OPS).json()
    return body["data"], body["meta"]


# ─── boundary_precision_check / bpc_sale_on_empty_slot_zero_onhand_rejected ─

def test_sale_on_empty_slot_rejected_insufficient_stock():
    """PRD §3.6: "The requested quantity must not exceed the slot's on_hand (the
    sum of remaining_units across the slot's AVAILABLE lots); if the FIFO walk runs
    short, the sale is refused with ERR_INSUFFICIENT_STOCK (HTTP 409)."

    Design: Difficulty/boundary_precision_check/bpc_sale_on_empty_slot_zero_onhand_rejected
    """
    set_clock("2026-06-06T00:00:00Z")
    host = make_host(name="Empty Host", contact_email="e@x.com")
    prod = make_product(sku="EMP", name="Empty Item", category="SNACK", unit_cost_cents=30)
    machine = make_machine(host["id"], asset_tag="M-11", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="J1",
                     capacity=10, par_level=10, price_cents=100)
    # Slot never restocked -> on_hand 0.
    res = api_client.create_sale(
        {"machine_id": machine["id"], "slot_id": slot["id"], "quantity": 1, "payment_method": "CASHLESS"},
        FIELD_OPS)
    validate_error(res, "ERR_INSUFFICIENT_STOCK", expected_status=409)


def test_sale_exceeding_onhand_rejected_insufficient_stock():
    """PRD §3.6: "The requested quantity must not exceed the slot's on_hand (the
    sum of remaining_units across the slot's AVAILABLE lots); if the FIFO walk runs
    short, the sale is refused with ERR_INSUFFICIENT_STOCK (HTTP 409)."

    A slot stocked with exactly 3 units rejects a qty-4 sale.

    Design: Difficulty/boundary_precision_check/bpc_sale_on_empty_slot_zero_onhand_rejected
    """
    set_clock("2026-06-06T00:00:00Z")
    host = make_host(name="Short Host", contact_email="sh@x.com")
    prod = make_product(sku="SHORT", name="Short", category="SNACK", unit_cost_cents=30)
    machine = make_machine(host["id"], asset_tag="M-11b", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="J1",
                     capacity=10, par_level=10, price_cents=100)
    driver = make_driver(full_name="Sh Drv", employee_code="EMPshort")
    route = make_route(driver["id"], "2026-06-06T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 3)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])

    res = api_client.create_sale(
        {"machine_id": machine["id"], "slot_id": slot["id"], "quantity": 4, "payment_method": "CASHLESS"},
        FIELD_OPS)
    validate_error(res, "ERR_INSUFFICIENT_STOCK", expected_status=409)


# ─── compensating_invariant / ci_sale_void_conserves_unit_inventory ────────

def _slot_one_lot(units=12, price=100):
    set_clock("2026-06-11T00:00:00Z")
    host = make_host(name="Inv Host", contact_email="inv@x.com")
    prod = make_product(sku="INV", name="Inv Item", category="SNACK", unit_cost_cents=40)
    machine = make_machine(host["id"], asset_tag="M-16", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="N1",
                     capacity=20, par_level=20, price_cents=price)
    driver = make_driver(full_name="Ina", employee_code="EMP16")
    route = make_route(driver["id"], "2026-06-11T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, units)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])
    return machine, slot


def test_void_restores_drawn_units_conserving_onhand():
    """PRD §3.6: "A void is a full compensating reversal: it restores
    remaining_units to each lot recorded in lot_consumption_json (reversing the
    FIFO draw), reverts to AVAILABLE any lot that this sale had marked DEPLETED,
    recomputes the affected slot's on_hand, and re-derives the machine's
    stock_status."

    Design: Difficulty/compensating_invariant/ci_sale_void_conserves_unit_inventory
    """
    machine, slot = _slot_one_lot(units=12, price=100)
    sale = make_sale(machine["id"], slot["id"], 5, "CASHLESS")
    after_sale = validate_success(api_client.get_slot(slot["id"], FIELD_OPS), 200)
    assert after_sale["on_hand"] == 7, after_sale

    validate_success(api_client.void_sale(sale["id"], FIELD_OPS), 200)
    after_void = validate_success(api_client.get_slot(slot["id"], FIELD_OPS), 200)
    assert after_void["on_hand"] == 12, after_void


def test_void_reverts_consumed_lot_to_available():
    """PRD §3.6: "it restores remaining_units to each lot recorded in
    lot_consumption_json (reversing the FIFO draw), reverts to AVAILABLE any lot
    that this sale had marked DEPLETED".

    Design: Difficulty/compensating_invariant/ci_sale_void_conserves_unit_inventory
    """
    machine, slot = _slot_one_lot(units=12, price=100)
    sale = make_sale(machine["id"], slot["id"], 5, "CASHLESS")
    validate_success(api_client.void_sale(sale["id"], FIELD_OPS), 200)
    lots, _ = _list_slot_lots(slot["id"])
    # The single lot is back to AVAILABLE with its full 12 units.
    assert len(lots) == 1, lots
    lot = lots[0]
    assert lot["status"] == "AVAILABLE", lot
    assert lot["remaining_units"] == 12, lot


# ─── compensating_invariant / ci_cash_sale_void_conserves_vault_cash ───────

def _cash_slot():
    set_clock("2026-06-12T00:00:00Z")
    host = make_host(name="Cash Host", contact_email="cash@x.com")
    prod = make_product(sku="CSH", name="Cash Item", category="BEVERAGE", unit_cost_cents=50)
    machine = make_machine(host["id"], asset_tag="M-17", machine_type="BEVERAGE_VENDOR",
                           cash_capacity_cents=100000, cash_alert_threshold_pct=0.80)
    slot = make_slot(machine["id"], prod["id"], slot_code="O1",
                     capacity=20, par_level=20, price_cents=200)
    driver = make_driver(full_name="Cas H", employee_code="EMP17")
    route = make_route(driver["id"], "2026-06-12T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, 10)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])
    return machine, slot


def test_cash_sale_then_void_conserves_vault_cash():
    """PRD §3.6: "If the voided sale's payment_method was CASH, the machine's
    cash_on_hand_cents is decreased by gross_cents and the cash posture is
    re-derived."
    PRD §3.6: "If the payment_method is CASH, the machine's cash_on_hand_cents is
    increased by gross_cents and the cash posture is re-derived".

    Design: Difficulty/compensating_invariant/ci_cash_sale_void_conserves_vault_cash
    """
    machine, slot = _cash_slot()
    sale = make_sale(machine["id"], slot["id"], 3, "CASH")  # gross 600
    after_sale = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert after_sale["cash_on_hand_cents"] == 600, after_sale

    validate_success(api_client.void_sale(sale["id"], FIELD_OPS), 200)
    after_void = validate_success(api_client.get_machine(machine["id"], FIELD_OPS), 200)
    assert after_void["cash_on_hand_cents"] == 0, after_void


def test_void_flips_sale_settlement_status_to_void():
    """PRD §3.6: "A settled sale may be voided by a FieldOps operator, which
    advances the sale SETTLED -> VOID; it requires the sale's settlement_status to
    be SETTLED, or it is rejected with ERR_SALE_NOT_SETTLED (HTTP 409)."

    Design: Difficulty/compensating_invariant/ci_cash_sale_void_conserves_vault_cash
    """
    machine, slot = _cash_slot()
    sale = make_sale(machine["id"], slot["id"], 3, "CASH")
    voided = validate_success(api_client.void_sale(sale["id"], FIELD_OPS), 200)
    assert voided["settlement_status"] == "VOID", voided
