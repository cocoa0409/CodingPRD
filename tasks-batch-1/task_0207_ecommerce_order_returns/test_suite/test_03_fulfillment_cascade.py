"""Shipment lifecycle and fulfillment cascade (PRD §3.5).

Difficulty queue: transitive_cascade (ship → commit → inventory → fulfillment),
non_linear_state_machine (parallel payment/fulfillment axes).
Corner queue: state_machines (partial-shipment bubble-up, cancel keeps HELD).
"""
from test_helpers import fixtures as fx


def test_ship_cascades_commit_decrement_and_fulfillment(api):
    """PRD §3.5: "Shipping triggers a three-link cascade: first, each referenced
    Reservation transitions from HELD to COMMITTED; second, each committed
    reservation decrements its InventoryItem's on_hand_qty by the reservation's qty;
    third, each touched item's available_qty is recomputed."
    PRD §3.5: "re-derives the order's fulfillment_status, which becomes SHIPPED once
    every non-backordered unit has shipped and PARTIALLY_SHIPPED otherwise."

    Design: Difficulty/transitive_cascade/ship_cascades_reservation_commit_to_inventory_to_fulfillment_depth3
    """
    ctx = fx.setup_captured_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=4, on_hand_qty=10)
    shipment, res_id = fx.create_pending_shipment(
        ctx["order"]["id"], ctx["warehouse"]["id"], ctx["line"]["id"], 4)
    fx.get_success_data(api.ship_shipment(shipment["id"], fx.OP))

    reservation = fx.get_reservation(res_id)
    assert reservation["status"] == "COMMITTED", "link1: reservation committed"

    inv = fx.get_inventory(ctx["inventory"]["id"])
    assert inv["on_hand_qty"] == 6, "link2: 10 - 4 committed"
    assert inv["available_qty"] == 6, "link2b: no remaining held reservation"

    order_after = fx.get_order(ctx["order"]["id"])
    assert order_after["fulfillment_status"] == "SHIPPED", "link3: bubble-up re-derive"


def test_ship_sets_order_line_shipped_qty(api):
    """PRD §3.5: "The system then recomputes each affected OrderLine's shipped_qty —
    the sum of shipment-line quantities across that line's shipments whose parcel
    status is SHIPPED or DELIVERED".

    Design: Difficulty/transitive_cascade/ship_cascades_reservation_commit_to_inventory_to_fulfillment_depth3
    """
    ctx = fx.setup_captured_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=4, on_hand_qty=10)
    shipment, _ = fx.create_pending_shipment(
        ctx["order"]["id"], ctx["warehouse"]["id"], ctx["line"]["id"], 4)
    fx.get_success_data(api.ship_shipment(shipment["id"], fx.OP))

    line_after = fx.get_order_line(ctx["line"]["id"])
    assert line_after["shipped_qty"] == 4


def test_capture_advances_payment_only_fulfillment_stays_unfulfilled(api):
    """PRD §3.4: "Capturing payment is permitted only when payment_status is
    AUTHORIZED; it freezes the captured base by setting captured_total_cents to the
    current grand_total_cents, advances payment_status from AUTHORIZED to CAPTURED".
    PRD §2.5: "an Order carries two independent state dimensions that evolve on
    separate axes."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions_evolve_independently
    """
    ctx = fx.setup_authorized_order(
        product_overrides={"unit_price_cents": 3000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10)
    after_capture = fx.capture(ctx["order"]["id"])
    assert after_capture["payment_status"] == "CAPTURED"
    assert after_capture["fulfillment_status"] == "UNFULFILLED", \
        "capture does not advance the fulfillment axis"


def test_ship_advances_fulfillment_only_payment_stays_captured(api):
    """PRD §3.5: "re-derives the order's fulfillment_status, which becomes SHIPPED
    once every non-backordered unit has shipped".
    PRD §2.5: "The two dimensions advance through different triggers described in
    §3, and the fulfillment dimension is re-derived from the underlying shipments
    whenever a parcel's own status changes."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions_evolve_independently
    """
    ctx = fx.setup_captured_order(
        product_overrides={"unit_price_cents": 3000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10)
    shipment, _ = fx.create_pending_shipment(
        ctx["order"]["id"], ctx["warehouse"]["id"], ctx["line"]["id"], 1)
    fx.get_success_data(api.ship_shipment(shipment["id"], fx.OP))

    order_after = fx.get_order(ctx["order"]["id"])
    assert order_after["payment_status"] == "CAPTURED", \
        "shipping does not move the payment axis"
    assert order_after["fulfillment_status"] == "SHIPPED"


def test_partial_shipment_sets_partially_shipped(api):
    """PRD §3.5: "re-derives the order's fulfillment_status, which becomes SHIPPED
    once every non-backordered unit has shipped and PARTIALLY_SHIPPED otherwise."
    PRD §3.5: "The system then recomputes each affected OrderLine's shipped_qty".

    Design: Corner/state_machines/partial_shipment_sets_partially_shipped_bubble_up
    """
    customer, w1, w2, product = fx.setup_two_warehouse_catalog(
        w1_on_hand=5, w2_on_hand=10, w1_priority=1, w2_priority=2)
    order = fx.create_cart(customer["id"])
    line = fx.add_line(order["id"], customer["id"], product["id"], 8)
    fx.checkout(order["id"], customer["id"])
    fx.capture(order["id"])

    # Ship only the priority-1 (W1) reservation of qty 5.
    shipment, _ = fx.create_pending_shipment(order["id"], w1["id"], line["id"], 5)
    fx.get_success_data(api.ship_shipment(shipment["id"], fx.OP))

    order_after = fx.get_order(order["id"])
    line_after = fx.get_order_line(line["id"])
    assert line_after["shipped_qty"] == 5
    assert order_after["fulfillment_status"] == "PARTIALLY_SHIPPED"


def test_cancel_pending_shipment_keeps_reservation_held(api):
    """PRD §3.5: "Cancelling a parcel is permitted only when the shipment is
    PENDING; it sets the parcel to CANCELLED and removes its shipment lines, but
    deliberately leaves the referenced reservations in HELD status so they remain
    re-shippable — a cancelled pending parcel does not release stock."

    Design: Corner/state_machines/cancel_pending_shipment_keeps_reservations_held
    """
    ctx = fx.setup_captured_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10)
    shipment, res_id = fx.create_pending_shipment(
        ctx["order"]["id"], ctx["warehouse"]["id"], ctx["line"]["id"], 1)
    cancelled = fx.get_success_data(api.cancel_shipment(shipment["id"], fx.OP))
    assert cancelled["status"] == "CANCELLED"

    reservation = fx.get_reservation(res_id)
    assert reservation["status"] == "HELD", "cancel does not RELEASE the reservation"
