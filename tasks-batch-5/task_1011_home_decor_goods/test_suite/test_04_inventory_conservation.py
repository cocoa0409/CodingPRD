"""Inventory conservation: reserve→cancel release, the full conservation
invariant, the zero-availability reservation edge, and allocation adjust."""
from test_helpers import (
    validate_error, ApiErrorId, new_store, new_product, new_inventory,
    new_order, add_line, cancel_order, get_inventory, adjust_inventory,
    api_client, TEST_USERS,
)

ASSOCIATE = TEST_USERS["associate_headers"]


# ─── order_cancel_release_reservation_depth2 (queue A) ───

def _reserve_three_then_cancel():
    store = new_store(name="Store CB1")
    product = new_product(sku="SKU-CB1", name="Bowl Set", category="KITCHEN",
                          base_price_cents=2000, clearance_floor_cents=200,
                          first_received_at="2026-06-25T00:00:00Z")
    inv = new_inventory(store["id"], product["id"], 10)
    order = new_order(store["id"], "CARRYOUT")
    add_line(order["id"], product["id"], 3)
    cancelled = cancel_order(order["id"])
    return inv, order, cancelled


def test_cancel_releases_reserved_units():
    """PRD §3.5: "Cancellation fires CASCADE-B: for each line, the reserved units
    are released back from `reserved_qty` into `on_hand_qty`, and each affected
    store-inventory row refreshes its owning product's `updated_at`."

    Design: Difficulty/transitive_cascade/order_cancel_release_reservation_depth2
    """
    inv, _, cancelled = _reserve_three_then_cancel()
    assert cancelled["fulfillment_status"] == "CANCELLED", f"got {cancelled['fulfillment_status']}"
    after = get_inventory(inv["id"])
    assert after["reserved_qty"] == 0, f"expected reserved 0, got {after['reserved_qty']}"


def test_cancel_returns_units_to_on_hand():
    """PRD §2.7: "Adding a line moves units from available to reserved; cancelling
    an order moves them back from reserved to available".

    Design: Difficulty/transitive_cascade/order_cancel_release_reservation_depth2
    """
    inv, _, _ = _reserve_three_then_cancel()
    after = get_inventory(inv["id"])
    assert after["on_hand_qty"] == 10, f"expected on_hand back to 10, got {after['on_hand_qty']}"


# ─── inventory_units_conserved_reserve_then_cancel (queue A) ───

def _reserve_four_then_cancel():
    store = new_store(name="Store CI1")
    product = new_product(sku="SKU-CI1", name="Duvet", category="TEXTILE",
                          base_price_cents=6000, clearance_floor_cents=500,
                          first_received_at="2026-06-25T00:00:00Z")
    inv = new_inventory(store["id"], product["id"], 10)
    order = new_order(store["id"], "CARRYOUT")
    add_line(order["id"], product["id"], 4)
    cancel_order(order["id"])
    return inv


def test_allocation_and_on_hand_conserved_after_compensation():
    """PRD §2.7: "For each store-inventory row, the total allocation always equals
    the sum of the units available, reserved, and sold: `allocated_qty` equals
    `on_hand_qty` plus `reserved_qty` plus `sold_qty`."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_reserve_then_cancel
    """
    inv = _reserve_four_then_cancel()
    after = get_inventory(inv["id"])
    assert after["allocated_qty"] == 10, f"expected allocated 10, got {after['allocated_qty']}"
    assert after["on_hand_qty"] == 10, f"expected on_hand 10, got {after['on_hand_qty']}"


def test_reserved_and_sold_zero_after_compensation():
    """PRD §2.7: "Units move between these buckets but are never created or
    destroyed except by an explicit allocation adjustment."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_reserve_then_cancel
    """
    inv = _reserve_four_then_cancel()
    after = get_inventory(inv["id"])
    assert after["reserved_qty"] == 0, f"expected reserved 0, got {after['reserved_qty']}"
    assert after["sold_qty"] == 0, f"expected sold 0, got {after['sold_qty']}"


# ─── inventory_reserve_at_zero_availability (queue A) ───

def _drive_availability_to_zero():
    store = new_store(name="Store B2")
    product = new_product(sku="SKU-B2", name="Candle", category="SEASONAL",
                          base_price_cents=500, clearance_floor_cents=100,
                          first_received_at="2026-06-25T00:00:00Z")
    inv = new_inventory(store["id"], product["id"], 3)
    o1 = new_order(store["id"], "CARRYOUT")
    add_line(o1["id"], product["id"], 3)  # drives available to 0
    o2 = new_order(store["id"], "CARRYOUT")
    return store, product, inv, o2


def test_reserve_when_no_availability_rejected():
    """PRD §3.4: "If the store-inventory row does not hold enough available units to
    cover the requested quantity, the line is rejected with
    `ERR_INSUFFICIENT_INVENTORY`."

    Design: Difficulty/boundary_precision_check/inventory_reserve_at_zero_availability
    """
    _, product, _, o2 = _drive_availability_to_zero()
    resp = api_client.add_order_line(o2["id"], {"product_id": product["id"], "qty": 1}, ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)


def test_full_reservation_drives_on_hand_to_zero():
    """PRD §3.4: "When the line is accepted, the line's `unit_price_cents` is
    snapshotted from the product's `current_price_cents` at that moment, and the
    requested units move from `on_hand_qty` into `reserved_qty`."

    Design: Difficulty/boundary_precision_check/inventory_reserve_at_zero_availability
    """
    _, _, inv, _ = _drive_availability_to_zero()
    after = get_inventory(inv["id"])
    assert after["on_hand_qty"] == 0, f"expected on_hand 0, got {after['on_hand_qty']}"
    assert after["reserved_qty"] == 3, f"expected reserved 3, got {after['reserved_qty']}"


# ─── inventory_adjust_increases_allocation_and_on_hand (queue B) ───

def test_adjust_raises_allocated_and_on_hand():
    """PRD §3.2: "a `MerchandisingManager` can adjust an allocation to receive more
    stock or shrink it by supplying a signed `delta_qty`; the adjustment adds
    `delta_qty` to both `allocated_qty` and `on_hand_qty`, and it must not drive
    `on_hand_qty` below zero."

    Design: Corner/endpoints/inventory_adjust_increases_allocation_and_on_hand
    """
    store = new_store(name="Store EP1")
    product = new_product(sku="SKU-EP1", name="Stool", category="FURNITURE",
                          base_price_cents=3000, clearance_floor_cents=300,
                          first_received_at="2026-06-25T00:00:00Z")
    inv = new_inventory(store["id"], product["id"], 5)
    adjusted = adjust_inventory(inv["id"], 3)
    assert adjusted["allocated_qty"] == 8, f"expected allocated 8, got {adjusted['allocated_qty']}"
    assert adjusted["on_hand_qty"] == 8, f"expected on_hand 8, got {adjusted['on_hand_qty']}"
