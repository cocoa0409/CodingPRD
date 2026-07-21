"""Order fulfillment/payment state machine: invalid transitions, parallel axes (PRD §3.2-3.4)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_fixture, create_order, add_line, quote, confirm,
)

SM = TEST_USERS["sm_headers"]


def test_confirm_draft_order_returns_invalid_state(api):
    """PRD §3.3: "Confirming an order acts on a `QUOTED` order and advances it to `CONFIRMED`."
    PRD §2.8: "the generic "resource is not in a state that permits this transition" guard
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/confirm_draft_order_returns_invalid_state
    """
    order = create_order(api, customer_name="DRF")
    resp = api.confirm_order(order["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_already_cancelled_order_returns_invalid_state(api):
    """PRD §2.8: "the generic "resource is not in a state that permits this transition" guard
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/cancel_already_cancelled_order_returns_invalid_state
    """
    order = create_order(api, customer_name="TC")
    validate_success(api.cancel_order(order["id"], SM), 200)
    resp = api.cancel_order(order["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_add_line_to_quoted_order_returns_order_not_draft(api):
    """PRD §3.2: "Lines may be added only while the order's `fulfillment_status` is `DRAFT`;
    attempting to add a line to an order in any other fulfillment state is rejected with
    `ERR_ORDER_NOT_DRAFT`."

    Design: Corner/state_machines/add_line_to_quoted_order_returns_order_not_draft
    """
    fx = create_fixture(api, sku_base="F-ND", base_price_cents=5000, base_wattage=40)
    order = create_order(api, customer_name="ND")
    add_line(api, order["id"], fx["id"], quantity=1)
    quote(api, order["id"])
    resp = api.add_order_line(order["id"], {"fixture_model_id": fx["id"], "quantity": 1}, SM)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DRAFT.value)


def test_confirm_reflects_immediately_in_read(api):
    """PRD §3.3: "Confirming an order acts on a `QUOTED` order and advances it to `CONFIRMED`."

    Design: Corner/consistency_model/immediate_consistency_confirm_reflects_in_read
    """
    fx = create_fixture(api, sku_base="F-IM", base_price_cents=5000, base_wattage=40)
    order = create_order(api, customer_name="IM")
    add_line(api, order["id"], fx["id"], quantity=1)
    quote(api, order["id"])
    confirm(api, order["id"])
    data = validate_success(api.get_order(order["id"], SM), 200)
    assert data["fulfillment_status"] == "CONFIRMED"


def test_deposit_advances_payment_axis_leaving_fulfillment_quoted(api):
    """PRD §3.4: "The payment axis moves independently of fulfillment."
    PRD §3.4: "A deposit is accepted only when the order's `payment_status` is `UNPAID` and
    its `fulfillment_status` is either `QUOTED` or `CONFIRMED`; it advances the payment axis
    from `UNPAID` to `DEPOSIT_PAID` and adds `amount_cents` to the order's running
    `amount_paid_cents`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_axes
    """
    fx = create_fixture(api, sku_base="F-PAR", base_price_cents=5000, base_wattage=40)
    order = create_order(api, customer_name="P")
    add_line(api, order["id"], fx["id"], quantity=1)
    quote(api, order["id"])
    data = validate_success(api.pay_order(order["id"], {"kind": "DEPOSIT", "amount_cents": 1000}, SM), 200)
    assert data["payment_status"] == "DEPOSIT_PAID"
    assert data["fulfillment_status"] == "QUOTED"


def test_confirm_advances_fulfillment_axis_leaving_payment_deposit_paid(api):
    """PRD §3.4: "The payment axis moves independently of fulfillment."
    PRD §3.3: "Confirming an order acts on a `QUOTED` order and advances it to `CONFIRMED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_axes
    """
    fx = create_fixture(api, sku_base="F-PAR2", base_price_cents=5000, base_wattage=40)
    order = create_order(api, customer_name="P")
    add_line(api, order["id"], fx["id"], quantity=1)
    quote(api, order["id"])
    api.pay_order(order["id"], {"kind": "DEPOSIT", "amount_cents": 1000}, SM)
    data = validate_success(api.confirm_order(order["id"], SM), 200)
    assert data["payment_status"] == "DEPOSIT_PAID"
    assert data["fulfillment_status"] == "CONFIRMED"
