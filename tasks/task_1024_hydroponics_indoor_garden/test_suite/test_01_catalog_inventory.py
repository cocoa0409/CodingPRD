"""Catalog products, inventory lots, the reservation cascade, and the reserve→
release conservation invariant."""
import pytest

from test_helpers import (
    validate_success, validate_error, assert_product,
    api_client, create_product_payload,
    new_stocked_product, new_customer, new_retail_order, confirm_order, cancel_order,
    receive_lot, new_product, order_line, TEST_USERS, MISSING_UUID,
    make_customer_headers,
)

ADMIN = TEST_USERS["store_admin_headers"]


# ─── Corner: entities ─────────────────────────────────────────────────────
def test_create_product_returns_all_fields(api):
    """PRD §3.1: "A `StoreAdmin` seeds the catalog by creating a **product**,
    supplying a `sku_code` (a human SKU that must be unique across the catalog),
    a display `name`, a `category` of `SYSTEM`, `LIGHTING`, `NUTRIENT`,
    `CONSUMABLE`, or `ACCESSORY`, and a `unit_price_cents` list price that must be
    greater than zero."
    PRD §2.4: "`version`: an integer that starts at creation and increments by one
    on every mutation."

    Design: Corner/entities/product_creation_returns_all_fields
    """
    res = api.create_product(
        create_product_payload(sku_code="SYS-A", name="Tower", category="SYSTEM",
                               unit_price_cents=12000),
        ADMIN,
    )
    product = validate_success(res, expected_status=201)
    assert_product(product)
    assert product["category"] == "SYSTEM"
    assert product["version"] == 1


def test_new_product_empty_stock_flags_reorder(api):
    """PRD §3.1: "A newly created product has no stock: its `total_available_units`
    is 0, and its `reorder_flag` is true exactly when its `reorder_threshold` is
    greater than 0."

    Design: Corner/entities/product_computed_reorder_flag_true_when_empty
    """
    res = api.create_product(
        create_product_payload(sku_code="SYS-B", name="Shelf", category="SYSTEM",
                               unit_price_cents=5000, reorder_threshold=5),
        ADMIN,
    )
    product = validate_success(res, expected_status=201)
    assert product["total_available_units"] == 0
    assert product["reorder_flag"] is True


def test_get_product_not_found(api):
    """PRD §2.9: "the identifiers are resolved strictly left to right, and the
    request is rejected with `ERR_NOT_FOUND` at the first identifier in the path
    that does not correspond to an existing resource, before any deeper resource
    is examined."

    Design: Corner/entities/get_product_not_found_returns_404
    """
    res = api.get_product(MISSING_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


# ─── Difficulty: transitive_cascade / confirm reserves → deplete → reorder ─
def _setup_two_lot_product_and_order():
    """Product (reorder_threshold 10) with lots L1(A-001, 5) then L2(A-002, 8);
    a customer with a DRAFT retail order for 5 units. Returns
    (customer, product, lot1, lot2, order)."""
    customer = new_customer()
    product = new_product(sku_code="SYS-3", name="NFT Channel", category="SYSTEM",
                          unit_price_cents=4000, reorder_threshold=10)
    lot1 = receive_lot(product["id"], lot_code="A-001", quantity_on_hand=5)
    lot2 = receive_lot(product["id"], lot_code="A-002", quantity_on_hand=8)
    order = new_retail_order(customer["id"], [order_line(product["id"], 5)])
    return customer, product, lot1, lot2, order


def test_confirm_depletes_first_lot(api):
    """PRD §3.5: "When stock suffices, the system reserves each line against the
    product's lots using the allocation waterfall: it walks the lots in
    `created_at` ascending then `lot_code` ascending order, and at each lot takes
    the smaller of the units still needed and that lot's `quantity_available`,
    adds that amount to the lot's `quantity_reserved`, recomputes the lot's
    `quantity_available`, and moves on until the line's need reaches zero."
    PRD §3.5: "Any lot whose `quantity_available` falls to 0 transitions
    `ACTIVE → DEPLETED`."

    Design: Difficulty/transitive_cascade/confirm_reserves_lot_depletes_flips_reorder
    """
    customer, product, lot1, lot2, order = _setup_two_lot_product_and_order()
    confirm_order(order["id"], customer["id"])

    refetched = validate_success(api.get_product(product["id"], ADMIN))
    lots, _meta = _lots(api, product["id"])
    lot1_after = _by_id(lots, lot1["id"])
    assert lot1_after["quantity_available"] == 0
    assert lot1_after["status"] == "DEPLETED"


def test_confirm_depletion_flips_reorder_flag(api):
    """PRD §3.5: "Each affected product then recomputes `total_available_units`,
    and if that value drops below the product's `reorder_threshold`, its
    `reorder_flag` flips to true."

    Design: Difficulty/transitive_cascade/confirm_reserves_lot_depletes_flips_reorder
    """
    customer, product, lot1, lot2, order = _setup_two_lot_product_and_order()
    confirm_order(order["id"], customer["id"])

    refetched = validate_success(api.get_product(product["id"], ADMIN))
    assert refetched["total_available_units"] == 8
    assert refetched["reorder_flag"] is True


# ─── Difficulty: compensating_invariant / reserve then cancel conserves ────
def _setup_single_lot_confirmed_order():
    customer = new_customer()
    product = new_product(sku_code="SYS-7", name="Bucket Kit", category="SYSTEM",
                          unit_price_cents=3000, reorder_threshold=10)
    lot = receive_lot(product["id"], lot_code="L-1", quantity_on_hand=5)
    order = new_retail_order(customer["id"], [order_line(product["id"], 5)])
    confirm_order(order["id"], customer["id"])
    return customer, product, lot, order


def test_cancel_confirmed_order_restores_lot(api):
    """PRD §3.5: "Cancelling a `CONFIRMED` order releases each reserved lot: the
    reserved amount is subtracted from that lot's `quantity_reserved`, its
    `quantity_available` is recomputed, and any `DEPLETED` lot whose
    `quantity_available` rises above 0 reverts `DEPLETED → ACTIVE`."

    Design: Difficulty/compensating_invariant/reserve_then_cancel_conserves_on_hand
    """
    customer, product, lot, order = _setup_single_lot_confirmed_order()
    cancel_order(order["id"], customer["id"])

    lots, _meta = _lots(api, product["id"])
    lot_after = _by_id(lots, lot["id"])
    assert lot_after["quantity_on_hand"] == 5
    assert lot_after["quantity_reserved"] == 0
    assert lot_after["quantity_available"] == 5
    assert lot_after["status"] == "ACTIVE"


def test_cancel_confirmed_order_restores_product_total(api):
    """PRD §3.5: "Each affected product recomputes `total_available_units` and its
    `reorder_flag`."
    PRD §2.7: "`total_available_units` is the sum of `quantity_available` across
    the product's lots whose `status` is `ACTIVE`; lots in any other status are
    excluded from that sum."

    Design: Difficulty/compensating_invariant/reserve_then_cancel_conserves_on_hand
    """
    customer, product, lot, order = _setup_single_lot_confirmed_order()
    cancel_order(order["id"], customer["id"])

    refetched = validate_success(api.get_product(product["id"], ADMIN))
    assert refetched["total_available_units"] == 5


# ─── local helpers ────────────────────────────────────────────────────────
def _lots(api, product_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_inventory_lots(product_id, ADMIN))


def _by_id(items, item_id):
    for it in items:
        if it["id"] == item_id:
            return it
    raise AssertionError(f"lot {item_id} not found in list")
