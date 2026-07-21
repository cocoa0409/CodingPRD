"""Order state machine: the parallel payment/fulfillment axes and their initial/invalid states."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_member, create_bottle, create_order, pay_order,
    setup_bottle_order_created, unit_line, make_customer_headers, TEST_USERS,
)

STAFF = TEST_USERS["shop_staff_headers"]


# ── Difficulty: non_linear_state_machine / order_parallel_payment_and_fulfillment_axes ──

def test_pay_advances_payment_axis_to_paid(api):
    """PRD §3.4: "Paying an order is a single act that advances both status axes at once —
    `payment_status` from `UNPAID` to `PAID` and `fulfillment_status` from `PENDING` to
    `RESERVED`".

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
    """
    member, product, order = setup_bottle_order_created(api, unit_price_cents=3000)
    order = pay_order(api, member, order)
    assert order["payment_status"] == "PAID", order["payment_status"]


def test_pay_advances_fulfillment_axis_to_reserved(api):
    """PRD §3.4: "Paying an order is a single act that advances both status axes at once —
    `payment_status` from `UNPAID` to `PAID` and `fulfillment_status` from `PENDING` to
    `RESERVED`".

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
    """
    member, product, order = setup_bottle_order_created(api, unit_price_cents=3000)
    order = pay_order(api, member, order)
    assert order["fulfillment_status"] == "RESERVED", order["fulfillment_status"]


# ── Corner: state_machines / order_initial_state_unpaid_pending ──

def test_new_order_starts_unpaid_pending(api):
    """PRD §3.3: "At creation the order sits with `payment_status` of `UNPAID` and
    `fulfillment_status` of `PENDING`, and its `final_subtotal_cents` and `final_total_cents`
    remain null until fulfillment."

    Design: Corner/state_machines/order_initial_state_unpaid_pending
    """
    member, product, order = setup_bottle_order_created(api, unit_price_cents=2000)
    assert order["payment_status"] == "UNPAID"
    assert order["fulfillment_status"] == "PENDING"


# ── Corner: state_machines / fulfill_unpaid_order_returns_invalid_state ──

def test_fulfill_pending_order_rejected_invalid_state(api):
    """PRD §3.5: "Fulfillment is performed by `ShopStaff` on an order whose `fulfillment_status`
    is `RESERVED`, with a matching `expected_order_version`; a wrong state yields
    `ERR_INVALID_STATE` and a wrong version yields `ERR_STALE_VERSION`."

    Design: Corner/state_machines/fulfill_unpaid_order_returns_invalid_state
    """
    member, product, order = setup_bottle_order_created(api, unit_price_cents=2000)
    resp = api.fulfill_order(order["id"], {"expected_order_version": order["version"]}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
