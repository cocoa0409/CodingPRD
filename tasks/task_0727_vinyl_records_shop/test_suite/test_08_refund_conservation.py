"""Capture-then-cancel refund conserving store credit and loyalty points.

Queue A: compensating_invariant/order_refund_conserves_store_credit.
"""
from test_helpers import (
    validate_success,
    TEST_USERS, make_customer_headers,
    register_customer, create_product, create_inventory_item,
    seed_store_credit, open_order, add_line,
)

CLERK = TEST_USERS["store_clerk_headers"]


def _capture_then_cancel(api):
    """Buyer with 500 credit, ONLINE order one NM base-3000 copy, captured applying 500
    credit, then cancelled. Returns (buyer, order)."""
    buyer = register_customer(api, full_name="Refund Buyer")
    seed_store_credit(api, customer_id=buyer["id"], delta_cents=500, reason="seed credit")
    product = create_product(api, artist="Fleetwood Mac", title="Rumours", format="VINYL",
                             base_price_cents=3000)
    item = create_inventory_item(api, product_id=product["id"], is_used=False, condition_grade="NM")
    order = open_order(api, customer=buyer, channel="ONLINE")
    hdr = make_customer_headers(buyer["id"])
    add_line(api, order=order, customer=buyer, item=item)
    validate_success(api.authorize_payment(order["id"], hdr))
    validate_success(api.capture_payment(order["id"], {"credit_applied_cents": 500}, CLERK))
    validate_success(api.cancel_order(order["id"], CLERK))
    return buyer, order


def test_refund_returns_store_credit_to_pre_capture_value(api):
    """PRD §3.3: "When an order that has reached PAID is cancelled, the capture is
    compensated exactly: payment_status moves to REFUNDED, the previously applied
    credit_applied_cents is credited back to the buyer's store_credit_cents ... This
    conserves store credit and points precisely across a capture-then-cancel cycle."

    Design: Difficulty/compensating_invariant/order_refund_conserves_store_credit
    """
    buyer, order = _capture_then_cancel(api)
    hdr = make_customer_headers(buyer["id"])
    order_after = validate_success(api.get_order(order["id"], hdr))
    assert order_after["payment_status"] == "REFUNDED", f"got {order_after['payment_status']}"
    cust = validate_success(api.get_customer(buyer["id"], hdr))
    assert cust["store_credit_cents"] == 500, f"credit must return to 500, got {cust['store_credit_cents']}"


def test_refund_reverses_awarded_loyalty_points(api):
    """PRD §3.3: "the points_earned that were awarded are reversed out of loyalty_points,
    and loyalty_tier is recomputed. This conserves store credit and points precisely across
    a capture-then-cancel cycle."

    Design: Difficulty/compensating_invariant/order_refund_conserves_store_credit
    """
    buyer, order = _capture_then_cancel(api)
    hdr = make_customer_headers(buyer["id"])
    cust = validate_success(api.get_customer(buyer["id"], hdr))
    assert cust["loyalty_points"] == 0, f"points must reverse to 0, got {cust['loyalty_points']}"
