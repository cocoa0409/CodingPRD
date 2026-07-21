"""Inventory reservation, release-on-cancel cascade, and the unit-conservation
invariant available_qty + reserved_qty == on_hand_qty."""
from test_helpers import (
    validate_success,
    setup_reserved_order, cancel_order,
    assert_sku_inventory_invariant,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


# ── transitive_cascade / order_cancel_line_inventory ──────────
def test_cancel_voids_lines_and_zeroes_reservation(api):
    """PRD §3.3: "The cancellation cascades: every reserved line becomes `VOID`, and
    because each line becomes void, the reservation it held is released — the referenced
    SKU's reserved quantity decreases by that line's quantity and its available quantity
    is recomputed."

    Design: Difficulty/transitive_cascade/order_cancel_line_inventory
    """
    store, member, sku, order = setup_reserved_order(state_code="OR", list_price_cents=10000,
                                                     on_hand_qty=10, qty=3)
    canceled = cancel_order(order["id"])
    assert canceled["fulfillment_status"] == "CANCELED"
    sku_after = validate_success(api.get_sku(sku["id"], ADMIN), 200)
    assert sku_after["reserved_qty"] == 0, "released reservation returns to 0"


def test_cancel_recomputes_available_back_to_on_hand(api):
    """PRD §2.8: "The `available_qty` is derived as the on-hand count minus the reserved
    count, floored at zero so it is never negative."
    PRD §3.3: "the referenced SKU's reserved quantity decreases by that line's quantity and
    its available quantity is recomputed."

    Design: Difficulty/transitive_cascade/order_cancel_line_inventory
    """
    store, member, sku, order = setup_reserved_order(state_code="OR", list_price_cents=10000,
                                                     on_hand_qty=10, qty=3)
    cancel_order(order["id"])
    sku_after = validate_success(api.get_sku(sku["id"], ADMIN), 200)
    assert sku_after["available_qty"] == 10
    assert sku_after["on_hand_qty"] == 10


# ── compensating_invariant / inventory_units_conservation_reserve_cancel ──
def test_on_hand_unchanged_across_reserve_and_cancel(api):
    """PRD §2.8: "On-hand quantity changes only in two situations: it decreases by the
    fulfilled quantity when order lines are fulfilled, and it increases by the returned
    quantity when a return is approved and the goods are restocked."

    Design: Difficulty/compensating_invariant/inventory_units_conservation_reserve_cancel
    """
    store, member, sku, order = setup_reserved_order(state_code="OR", list_price_cents=10000,
                                                     on_hand_qty=8, qty=5)
    reserved = validate_success(api.get_sku(sku["id"], ADMIN), 200)
    assert reserved["on_hand_qty"] == 8
    assert reserved["reserved_qty"] == 5
    cancel_order(order["id"])
    after = validate_success(api.get_sku(sku["id"], ADMIN), 200)
    assert after["on_hand_qty"] == 8, "on_hand is conserved through reserve+cancel"
    assert after["reserved_qty"] == 0


def test_inventory_invariant_holds_after_cancel(api):
    """PRD §2.8: "The governing invariant is that available quantity plus reserved quantity
    always equals on-hand quantity."

    Design: Difficulty/compensating_invariant/inventory_units_conservation_reserve_cancel
    """
    store, member, sku, order = setup_reserved_order(state_code="OR", list_price_cents=10000,
                                                     on_hand_qty=8, qty=5)
    cancel_order(order["id"])
    after = validate_success(api.get_sku(sku["id"], ADMIN), 200)
    assert_sku_inventory_invariant(after)
    assert after["available_qty"] == 8


# ── Corner/consistency_model/order_reservation_immediately_visible ──
def test_reservation_immediately_visible_on_get(api):
    """PRD §2.8: "The `reserved_qty` is a derived figure: the sum of the quantities of all
    order lines that are currently in the `RESERVED` line state and reference this SKU,
    across every order."

    Design: Corner/consistency_model/order_reservation_immediately_visible
    """
    store, member, sku, order = setup_reserved_order(state_code="OR", list_price_cents=6000,
                                                     on_hand_qty=10, qty=4)
    sku_after = validate_success(api.get_sku(sku["id"], ADMIN), 200)
    assert sku_after["reserved_qty"] == 4
    assert sku_after["available_qty"] == 6
    assert sku_after["on_hand_qty"] == 10
