"""Cross-entity state dependencies: framing<->order, order<->loyalty."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_customer, create_product_with_lot, create_order, create_order_with_line,
    create_framing_order, submit_order, complete_picked_up_order, get_loyalty_account,
    make_customer_headers, set_clock,
)


def test_framing_approve_requires_linked_order_ready(api):
    """PRD §3.7: "approval requires that the linked retail order's
    fulfillment_status be either SUBMITTED or READY_FOR_PICKUP, otherwise
    ERR_LINKED_ORDER_NOT_READY."

    Design: Difficulty/cross_entity_state_dependency/framing_approve_requires_linked_order_ready
    """
    customer = create_customer()
    order = create_order(customer["id"])  # still BUILDING
    framing = create_framing_order(order["id"], customer["id"], width_in=20, height_in=20)
    resp = api.approve_framing(framing["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_LINKED_ORDER_NOT_READY)


def test_framing_approve_succeeds_when_linked_order_submitted(api):
    """PRD §3.7: "The customer approves the quote, moving the framing order from
    QUOTED to APPROVED; approval requires that the linked retail order's
    fulfillment_status be either SUBMITTED or READY_FOR_PICKUP, otherwise
    ERR_LINKED_ORDER_NOT_READY."

    Design: Difficulty/cross_entity_state_dependency/framing_approve_requires_linked_order_ready
    """
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=20, sell_mode="UNIT", unit_price_cents=100)
    order, _ = create_order_with_line(customer["id"], product["id"], requested_yards=1)
    submit_order(order["id"], customer["id"])
    framing = create_framing_order(order["id"], customer["id"], width_in=20, height_in=20)
    data = validate_success(api.approve_framing(framing["id"], make_customer_headers(customer["id"])))
    assert data["status"] == "APPROVED"


def test_pay_requires_sufficient_loyalty_points(api):
    """PRD §3.5: "If a positive number of points is being redeemed, the loyalty
    account's points_balance must be at least points_redeemed_on_order, otherwise
    ERR_INSUFFICIENT_POINTS"

    Design: Difficulty/cross_entity_state_dependency/order_pay_requires_loyalty_points_balance
    """
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=20, sell_mode="UNIT", unit_price_cents=800)
    order, _ = create_order_with_line(customer["id"], product["id"], requested_yards=1)
    submit_order(order["id"], customer["id"])
    resp = api.pay_order(
        order["id"], {"points_redeemed_on_order": 50}, make_customer_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS)


def test_pay_succeeds_when_points_balance_sufficient(api):
    """PRD §3.5: "on successful payment with redemption, points_redeemed increases
    by points_redeemed_on_order and points_balance is recomputed."

    Design: Difficulty/cross_entity_state_dependency/order_pay_requires_loyalty_points_balance
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=10, sell_mode="UNIT", unit_price_cents=30000)
    # Earn 300 points via a picked-up order.
    complete_picked_up_order(customer["id"], product["id"], requested_yards=1)
    order2, _ = create_order_with_line(customer["id"], product["id"], requested_yards=1)
    submit_order(order2["id"], customer["id"])
    data = validate_success(
        api.pay_order(order2["id"], {"points_redeemed_on_order": 50}, make_customer_headers(customer["id"]))
    )
    assert data["payment_status"] == "PAID"
    account = get_loyalty_account(customer["id"])
    assert account["points_redeemed"] == 50
