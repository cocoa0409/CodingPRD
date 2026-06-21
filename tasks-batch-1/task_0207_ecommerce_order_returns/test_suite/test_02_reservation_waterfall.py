"""Inventory reservation waterfall at checkout (PRD §3.3).

Difficulty queue: resource_temporal_overlap (aggregate capacity).
Corner queue: calculations (split across warehouses, partial backorder).
"""
from test_helpers import fixtures as fx


def test_split_across_warehouses_in_priority_order(api):
    """PRD §3.3: "These candidates are ordered first by their warehouse's
    fulfillment_priority ascending (priority 1 before priority 2)".
    PRD §3.3: "If no single warehouse covers the line but the cumulative
    availability across warehouses does, two or more HELD reservations are created,
    filling higher-priority warehouses first."
    PRD §3.3: "the line's reserved_qty is the ordered quantity minus whatever
    remains unfilled, and its backordered_qty is that remaining shortfall."

    Design: Corner/calculations/reservation_split_across_warehouses_in_priority_order
    """
    customer, w1, w2, product = fx.setup_two_warehouse_catalog(
        w1_on_hand=5, w2_on_hand=10, w1_priority=1, w2_priority=2)
    order = fx.create_cart(customer["id"])
    line = fx.add_line(order["id"], customer["id"], product["id"], 8)
    fx.checkout(order["id"], customer["id"])

    res_w1 = fx.get_line_reservations(line["id"], w1["id"])
    res_w2 = fx.get_line_reservations(line["id"], w2["id"])
    assert res_w1[0]["qty"] == 5, "priority-1 warehouse filled first to its capacity"
    assert res_w2[0]["qty"] == 3, "remaining 3 spill to priority-2 warehouse"

    line_after = fx.get_order_line(line["id"])
    assert line_after["reserved_qty"] == 8
    assert line_after["backordered_qty"] == 0


def test_partial_backorder_when_total_stock_insufficient(api):
    """PRD §3.3: "If the cumulative availability across all warehouses falls short
    of the line's quantity, the reserved quantity equals the total available and the
    backordered_qty carries the shortfall."
    PRD §3.3: "if any OrderLine has a backordered_qty greater than zero the
    fulfillment_status becomes BACKORDERED".

    Design: Corner/calculations/partial_backorder_when_total_stock_insufficient
    """
    customer, w1, w2, product = fx.setup_two_warehouse_catalog(
        w1_on_hand=5, w2_on_hand=1, w1_priority=1, w2_priority=2)
    order = fx.create_cart(customer["id"])
    line = fx.add_line(order["id"], customer["id"], product["id"], 8)
    after = fx.checkout(order["id"], customer["id"])

    line_after = fx.get_order_line(line["id"])
    assert line_after["reserved_qty"] == 6, "total available 5+1 reserved"
    assert line_after["backordered_qty"] == 2, "shortfall 8-6"
    assert after["fulfillment_status"] == "BACKORDERED"


def test_second_order_pushed_to_backorder_when_pool_held_by_first(api):
    """PRD §3.3: "The candidates for a line are the InventoryItem rows for the
    line's product_id whose available_qty is greater than 0."
    PRD §3.3: "If the cumulative availability across all warehouses falls short of
    the line's quantity, the reserved quantity equals the total available and the
    backordered_qty carries the shortfall."
    PRD §3.1: "available_qty, equal to on_hand_qty minus reserved_qty and floored at
    0 — the quantity reservable right now."

    Design: Difficulty/resource_temporal_overlap/inventory_aggregate_capacity_overlap_pushes_second_order_to_backorder
    """
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    product = fx.create_product(unit_price_cents=1000, tax_rate_bps=0, return_window_days=30)
    inventory = fx.stock_inventory(product["id"], warehouse["id"], 5)

    order_a = fx.create_cart(customer["id"])
    fx.add_line(order_a["id"], customer["id"], product["id"], 5)
    fx.checkout(order_a["id"], customer["id"])

    inv_after_a = fx.get_inventory(inventory["id"])
    assert inv_after_a["available_qty"] == 0, "order A holds all 5"

    order_b = fx.create_cart(customer["id"])
    line_b = fx.add_line(order_b["id"], customer["id"], product["id"], 3)
    order_b_after = fx.checkout(order_b["id"], customer["id"])

    line_b_after = fx.get_order_line(line_b["id"])
    assert line_b_after["reserved_qty"] == 0
    assert line_b_after["backordered_qty"] == 3
    assert order_b_after["fulfillment_status"] == "BACKORDERED"


def test_aggregate_capacity_available_qty_zero_after_first_order_holds_pool(api):
    """PRD §3.1: "reserved_qty, the sum of the quantities of reservations against
    that product-and-warehouse pair whose status is HELD or COMMITTED (and which
    never exceeds on_hand_qty), and available_qty, equal to on_hand_qty minus
    reserved_qty and floored at 0".

    Design: Difficulty/resource_temporal_overlap/inventory_aggregate_capacity_overlap_pushes_second_order_to_backorder
    """
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    product = fx.create_product(unit_price_cents=1000, tax_rate_bps=0, return_window_days=30)
    inventory = fx.stock_inventory(product["id"], warehouse["id"], 5)

    order_a = fx.create_cart(customer["id"])
    fx.add_line(order_a["id"], customer["id"], product["id"], 5)
    fx.checkout(order_a["id"], customer["id"])

    inv = fx.get_inventory(inventory["id"])
    assert inv["on_hand_qty"] == 5, "nothing shipped yet — physical stock unchanged"
    assert inv["reserved_qty"] == 5
    assert inv["available_qty"] == 0
