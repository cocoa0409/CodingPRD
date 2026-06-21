"""State-machine transitions and guards (PRD §3.2–§3.7).

Corner queue: state_machines (initial state, invalid transitions, terminal
lockdown, precondition enforcement, guarded transitions).
"""
from test_helpers import (
    fixtures as fx,
    validate_error,
    ApiErrorId,
    make_customer_headers,
    checkout_payload,
)

DELIVER_CLOCK = "2026-06-05T00:00:00Z"


def test_new_order_initial_state_cart_unfulfilled(api):
    """PRD §3.2: "The new Order begins in CART payment status and UNFULFILLED
    fulfillment status with every computed total at 0."
    PRD §2.4: "The version field is an integer that starts at its initial value".

    Design: Corner/state_machines/new_order_initial_state_cart_unfulfilled
    """
    customer = fx.create_customer()
    order = fx.create_cart(customer["id"])
    assert order["payment_status"] == "CART"
    assert order["fulfillment_status"] == "UNFULFILLED"
    assert order["version"] == 1


def test_checkout_empty_cart_rejected(api):
    """PRD §3.2: "the order must currently be in CART payment status with at least
    one OrderLine; an attempt to check out an order that is not in CART is an
    ERR_INVALID_STATE rejection."

    Design: Corner/state_machines/checkout_empty_cart_returns_invalid_state
    """
    customer = fx.create_customer()
    order = fx.create_cart(customer["id"])
    headers = make_customer_headers(customer["id"])
    version = fx.get_order(order["id"], customer["id"])["version"]
    resp = api.checkout_order(order["id"], checkout_payload(version), headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_checkout_already_authorized_order_rejected(api):
    """PRD §3.2: "an attempt to check out an order that is not in CART is an
    ERR_INVALID_STATE rejection."

    Design: Corner/state_machines/checkout_from_already_authorized_returns_invalid_state
    """
    ctx = fx.setup_authorized_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10)
    headers = make_customer_headers(ctx["customer"]["id"])
    version = fx.get_order(ctx["order"]["id"], ctx["customer"]["id"])["version"]
    resp = api.checkout_order(ctx["order"]["id"], checkout_payload(version), headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_deliver_pending_shipment_rejected(api):
    """PRD §3.5: "Marking a parcel delivered is also a WarehouseOperator action and
    is permitted only when the shipment is SHIPPED."

    Design: Corner/state_machines/deliver_pending_shipment_returns_invalid_state
    """
    ctx = fx.setup_captured_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10)
    shipment, _ = fx.create_pending_shipment(
        ctx["order"]["id"], ctx["warehouse"]["id"], ctx["line"]["id"], 1)
    resp = api.deliver_shipment(shipment["id"], fx.OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_settle_rejected_rma_is_invalid_state(api):
    """PRD §3.7: "Alternatively, a StoreAdmin may reject a REQUESTED return, which
    moves it to the terminal REJECTED status with no ledger movement and no effect on
    any order line's returned_qty."
    PRD §3.8: "Settlement is a StoreAdmin action permitted only on an APPROVED
    return".

    Design: Corner/state_machines/settle_rejected_rma_returns_invalid_state_terminal
    """
    fx.set_clock(DELIVER_CLOCK)
    ctx = fx.setup_delivered_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10, delivered_clock=DELIVER_CLOCK)
    rma = fx.open_return(ctx["order"]["id"], ctx["customer"]["id"],
                         "NO_LONGER_WANTED", "REFUND",
                         [{"order_line_id": ctx["line"]["id"], "return_qty": 1}])
    fx.get_success_data(api.reject_return(rma["id"], fx.ADMIN))
    resp = api.settle_return(rma["id"], fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_void_after_ship_blocked(api):
    """PRD §3.4: "Voiding is the alternative, and it too is permitted only when
    payment_status is AUTHORIZED, with the additional precondition that no shipment of
    the order is in SHIPPED or DELIVERED status — an authorized order cannot be voided
    once any of its goods are in transit or delivered."

    Design: Corner/state_machines/void_after_ship_blocked_invalid_state
    """
    ctx = fx.setup_shipped_order(
        product_overrides={"unit_price_cents": 1000, "tax_rate_bps": 0,
                           "return_window_days": 30},
        qty=1, on_hand_qty=10)
    resp = api.void_order(ctx["order"]["id"], fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
