"""Order parallel state axes and invalid-transition guards."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_customer, create_product_with_lot, create_order, create_order_with_line,
    submit_order, make_customer_headers,
)


def test_pay_advances_only_payment_axis(api):
    """PRD §3.5: "Paying an order advances payment_status from UNPAID to PAID"
    PRD §3.4: "Submitting an order advances fulfillment_status from BUILDING to
    SUBMITTED."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=50, sell_mode="UNIT", unit_price_cents=500)
    order, _ = create_order_with_line(customer["id"], product["id"], requested_yards=1)
    submit_order(order["id"], customer["id"])
    resp = api.pay_order(order["id"], {}, make_customer_headers(customer["id"]))
    data = validate_success(resp)
    assert data["payment_status"] == "PAID"
    assert data["fulfillment_status"] == "SUBMITTED"


def test_submitted_order_still_unpaid_before_pay(api):
    """PRD §3.4: "Submitting an order advances fulfillment_status from BUILDING to
    SUBMITTED."
    PRD §3.4: "and begins with fulfillment_status of BUILDING and payment_status of
    UNPAID."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_dimensions
    """
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=50, sell_mode="UNIT", unit_price_cents=500)
    order, _ = create_order_with_line(customer["id"], product["id"], requested_yards=1)
    submitted = submit_order(order["id"], customer["id"])
    assert submitted["fulfillment_status"] == "SUBMITTED"
    assert submitted["payment_status"] == "UNPAID"


def test_cancel_already_cancelled_order_invalid_state(api):
    """PRD §3.5: "Cancelling an order is permitted from BUILDING, SUBMITTED, or
    READY_FOR_PICKUP, and is refused with ERR_INVALID_STATE if the order is
    already PICKED_UP or CANCELLED."

    Design: Corner/state_machines/cancel_already_cancelled_order_invalid_state
    """
    customer = create_customer()
    order = create_order(customer["id"])
    api.cancel_order(order["id"], make_customer_headers(customer["id"]))
    resp = api.cancel_order(order["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
