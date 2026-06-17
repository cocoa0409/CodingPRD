"""Order lifecycle — the two independent status axes, the confirmation gate,
and the state-machine guards around add-line, cancel, and close.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS,
    create_customer, create_sofa_product, create_draft_order, add_line,
    pay_in_full, confirm, setup_order_with_line, setup_confirmed_paid_order,
    setup_delivered_order, file_return,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


# ─── Difficulty: Order's two independent axes ─────────────────────────────
def test_pay_in_full_settles_payment_axis_only(api):
    """PRD 2.6: "A transition on one axis never implicitly moves the other — for example,
    paying in full settles the payment dimension while leaving fulfillment_status
    untouched."
    PRD 3.4: "on success, payment_status moves UNPAID -> PAID_IN_FULL while the
    fulfillment dimension is untouched."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
    """
    customer, product, order, line = setup_order_with_line()
    paid = pay_in_full(order["id"])
    assert paid["payment_status"] == "PAID_IN_FULL", "payment axis advances"
    assert paid["fulfillment_status"] == "DRAFT", "fulfillment axis stays DRAFT"


def test_confirm_advances_fulfillment_axis_only(api):
    """PRD 2.6: "An Order advances along two independent axes that never share a value
    space."
    PRD 3.4: "Confirming an order advances fulfillment_status from DRAFT to CONFIRMED ..."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
    """
    customer, product, order, line = setup_order_with_line()
    pay_in_full(order["id"])
    confirmed = confirm(order["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED", "fulfillment axis advances"
    assert confirmed["payment_status"] == "PAID_IN_FULL", "payment axis stays settled"


# ─── Difficulty: confirm requires settled payment axis ────────────────────
def test_confirm_unpaid_order_rejected(api):
    """PRD 3.4: "confirming an order still `UNPAID` is rejected with
    `ERR_ORDER_NOT_SETTLED`."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_order_settled_payment_axis
    """
    customer, product, order, line = setup_order_with_line()
    assert order["payment_status"] == "UNPAID"
    res = api.confirm_order(order["id"], SA)
    validate_error(res, "ERR_ORDER_NOT_SETTLED")


def test_confirm_succeeds_once_paid_in_full(api):
    """PRD 3.4: "Confirmation requires the order ... to be already settled, meaning
    payment_status is FINANCED or PAID_IN_FULL ..."

    Second test for this instance: the same order confirms once settled.

    Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_order_settled_payment_axis
    """
    customer, product, order, line = setup_order_with_line()
    pay_in_full(order["id"])
    confirmed = confirm(order["id"])
    assert confirmed["fulfillment_status"] == "CONFIRMED"


# ─── Corner: confirm-twice invalid state ──────────────────────────────────
def test_confirm_already_confirmed_order_rejected(api):
    """PRD 3.4: "Confirmation requires the order to be in `DRAFT` (otherwise
    `ERR_INVALID_STATE`) ..."

    Design: Corner/state_machines/confirm_already_confirmed_order_returns_invalid_state
    """
    customer, product, order, line = setup_confirmed_paid_order()
    res = api.confirm_order(order["id"], SA)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: pay-in-full on empty order ───────────────────────────────────
def test_pay_in_full_empty_order_rejected(api):
    """PRD 3.4: "A SalesAssociate settles an unpaid order outright by paying it in full:
    the order ... must have at least one `ACTIVE` line (otherwise `ERR_EMPTY_ORDER`) ..."

    Design: Corner/state_machines/confirm_empty_order_returns_empty_order
    """
    customer = create_customer()
    order = create_draft_order(customer["id"])
    res = api.pay_in_full_order(order["id"], SA)
    validate_error(res, "ERR_EMPTY_ORDER")


# ─── Corner: cancel a delivered order ─────────────────────────────────────
def test_cancel_delivered_order_rejected(api):
    """PRD 3.11: "A SalesAssociate may cancel an order while its `fulfillment_status` is
    `DRAFT` or `CONFIRMED` ... a cancellation attempted from any other state is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_delivered_order_via_cancel_returns_invalid_state
    """
    customer, product, order, line, route, stop = setup_delivered_order()
    delivered = get_success_data(api.get_order(order["id"], SA))
    assert delivered["fulfillment_status"] == "DELIVERED"
    res = api.cancel_order(order["id"], SA)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: add line to a confirmed order ────────────────────────────────
def test_add_line_to_confirmed_order_rejected(api):
    """PRD 3.2: "both adding and removing a line are permitted only while the order's
    `fulfillment_status` is `DRAFT`, and any such attempt on a non-draft order is rejected
    with `ERR_ORDER_NOT_DRAFT`."

    Design: Corner/state_machines/add_line_to_confirmed_order_returns_order_not_draft
    """
    customer, product, order, line = setup_confirmed_paid_order()
    res = api.create_order_line({
        "order_id": order["id"], "product_id": product["id"],
        "fabric_code": "STANDARD", "size_code": "STD", "quantity": 1}, SA)
    validate_error(res, "ERR_ORDER_NOT_DRAFT")


def test_delete_line_on_confirmed_order_rejected(api):
    """PRD 3.2: "both adding and removing a line are permitted only while the order's
    `fulfillment_status` is `DRAFT`, and any such attempt on a non-draft order is rejected
    with `ERR_ORDER_NOT_DRAFT`."

    Second test for this instance: removal is frozen after confirmation too.

    Design: Corner/state_machines/add_line_to_confirmed_order_returns_order_not_draft
    """
    customer, product, order, line = setup_confirmed_paid_order()
    res = api.delete_order_line(line["id"], SA)
    validate_error(res, "ERR_ORDER_NOT_DRAFT")


# ─── Corner: close blocked by open returns ────────────────────────────────
def test_close_order_with_open_return_rejected(api):
    """PRD 3.11: "Closing requires the order to be `DELIVERED` (otherwise
    `ERR_INVALID_STATE`) and requires that no `ReturnRequest` on the order is still open —
    that is, none is in `REQUESTED` or `APPROVED` status; an outstanding open return
    blocks closing with `ERR_OPEN_RETURNS_EXIST`."

    Design: Corner/validations/close_order_with_open_return_returns_open_returns_exist
    """
    customer, product, order, line, route, stop = setup_delivered_order()
    file_return(line["id"], customer["id"], reason="DAMAGED")  # REQUESTED
    res = api.close_order(order["id"], SM)
    validate_error(res, "ERR_OPEN_RETURNS_EXIST")
