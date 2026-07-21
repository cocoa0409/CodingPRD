"""Order lifecycle: independent payment/fulfillment axes and invalid state transitions."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_submitted_retail_order, setup_paid_retail_order,
    create_customer, create_order, create_product_line_payload, TEST_USERS,
)

CS = TEST_USERS["counter_staff_headers"]


# ─── non_linear_state_machine / order_parallel_payment_fulfillment_axes ────
class TestOrderParallelAxes:
    def test_pay_advances_payment_axis_only(self, api):
        """PRD §3.5: "**Payment** moves the order `UNPAID → PAID` and is independent of
        fulfillment."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_axes
        """
        sc = setup_submitted_retail_order(requested_weight_g=300, received_weight_g=1000)
        order = validate_success(api.pay_order(sc["order"]["id"], {"payment_method": "EXTERNAL"}, CS), 200)
        assert order["payment_status"] == "PAID"
        assert order["fulfillment_status"] == "SUBMITTED"

    def test_fulfillment_axis_unchanged_after_payment_on_reread(self, api):
        """PRD §3.5: "**Payment** moves the order `UNPAID → PAID` and is independent of
        fulfillment."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_axes
        """
        sc = setup_submitted_retail_order(requested_weight_g=300, received_weight_g=1000)
        api.pay_order(sc["order"]["id"], {"payment_method": "EXTERNAL"}, CS)
        order = get_success_data(api.get_order(sc["order"]["id"], CS))
        assert order["payment_status"] == "PAID"
        assert order["fulfillment_status"] == "SUBMITTED"


# ─── Corner: state_machines / corner_pay_before_submit_invalid_state ───────
def test_pay_before_submit_rejected(api):
    """PRD §3.5: "Paying requires the order to be `SUBMITTED` (else `ERR_INVALID_STATE`) and
    still `UNPAID` (a second payment is rejected with `ERR_ALREADY_PAID`)."

    Design: Corner/state_machines/corner_pay_before_submit_invalid_state
    """
    customer = create_customer()
    order = create_order(customer["id"], "RETAIL")
    res = api.pay_order(order["id"], {"payment_method": "EXTERNAL"}, CS)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: state_machines / corner_fulfill_before_pay_returns_not_paid ───
def test_fulfill_before_pay_rejected(api):
    """PRD §3.5: "**Fulfillment** moves the order `SUBMITTED → FULFILLED` and requires the
    order to be `SUBMITTED` (else `ERR_INVALID_STATE`) and `PAID` (else `ERR_ORDER_NOT_PAID`)."

    Design: Corner/state_machines/corner_fulfill_before_pay_returns_not_paid
    """
    sc = setup_submitted_retail_order(requested_weight_g=200, received_weight_g=1000)
    res = api.fulfill_order(
        sc["order"]["id"],
        {"line_actuals": [{"line_id": sc["line"]["id"], "actual_cut_weight_g": 200}]}, CS)
    validate_error(res, "ERR_ORDER_NOT_PAID")


# ─── Corner: state_machines / corner_return_non_fulfilled_returns_not_fulfilled ──
def test_return_non_fulfilled_rejected(api):
    """PRD §3.6: "**Returning** an order applies only to a `FULFILLED` order (a return
    attempted on any other fulfillment state is rejected with `ERR_ORDER_NOT_FULFILLED`) that
    is also `PAID`, and moves it `FULFILLED → RETURNED`."

    Design: Corner/state_machines/corner_return_non_fulfilled_returns_not_fulfilled
    """
    customer = create_customer()
    order = create_order(customer["id"], "RETAIL")
    res = api.return_order(order["id"], CS)
    validate_error(res, "ERR_ORDER_NOT_FULFILLED")


# ─── Corner: state_machines / corner_pay_twice_returns_already_paid ────────
def test_pay_twice_rejected(api):
    """PRD §3.5: "Paying requires the order to be `SUBMITTED` (else `ERR_INVALID_STATE`) and
    still `UNPAID` (a second payment is rejected with `ERR_ALREADY_PAID`)."

    Design: Corner/state_machines/corner_pay_twice_returns_already_paid
    """
    sc = setup_paid_retail_order(requested_weight_g=200, received_weight_g=1000)
    res = api.pay_order(sc["order"]["id"], {"payment_method": "EXTERNAL"}, CS)
    validate_error(res, "ERR_ALREADY_PAID")


# ─── Corner: state_machines / corner_add_line_after_submit_not_draft ───────
def test_add_line_after_submit_rejected(api):
    """PRD §3.4: "Lines are added to a `DRAFT` order; adding a line to an order that is not
    `DRAFT` is rejected with `ERR_ORDER_NOT_DRAFT`."

    Design: Corner/state_machines/corner_add_line_after_submit_not_draft
    """
    sc = setup_submitted_retail_order(requested_weight_g=200, received_weight_g=1000)
    res = api.add_order_line(
        sc["order"]["id"],
        create_product_line_payload(sc["product"]["id"], requested_weight_g=100), CS)
    validate_error(res, "ERR_ORDER_NOT_DRAFT")
