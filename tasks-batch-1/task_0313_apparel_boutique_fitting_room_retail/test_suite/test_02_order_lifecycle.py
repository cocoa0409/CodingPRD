"""Sales-order parallel state axes and lifecycle transitions.

Queue A (Difficulty): non_linear_state_machine (sales order axes).
Queue B (Corner): state_machines (capture/cancel invalid states), consistency_model.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_boutique, create_customer, create_style, create_variant,
    setup_basic_retail_scenario, open_order_with_line,
    create_captured_order,
)

ASSOCIATE = TEST_USERS["store_associate_headers"]


# ─── Queue A: non_linear_state_machine ────────────────────────────────────

def test_payment_and_fulfillment_axes_advance_independently(api):
    """PRD §3.6: "Payment and fulfillment are two independent state axes on the same
    order."
    PRD §3.6: "Completing an order (fulfillment_status OPEN -> COMPLETED) is permitted
    only once payment_status is CAPTURED; completion makes the order return-eligible
    and stamps return_anchor_date with the boutique's current_business_date at that
    moment".

    After capture + complete the order reads payment_status=CAPTURED AND
    fulfillment_status=COMPLETED on two independent axes.

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_payment_and_fulfillment_axes
    """
    bq, cu, style, variant = setup_basic_retail_scenario(tax_rate_bps=875, list_price_cents=5000)
    captured, _ = create_captured_order(cu["id"], variant["id"], qty=1)
    assert captured["payment_status"] == "CAPTURED"
    assert captured["fulfillment_status"] == "OPEN"

    completed = validate_success(api.complete_order(captured["id"], ASSOCIATE), 200)
    assert completed["payment_status"] == "CAPTURED"
    assert completed["fulfillment_status"] == "COMPLETED"


def test_authorize_leaves_fulfillment_open_on_payment_axis(api):
    """PRD §3.6: "Authorizing an order (payment_status UNPAID -> AUTHORIZED) is
    permitted only when the order's fulfillment_status is OPEN, the order has at least
    one order line, and the customer's status is ACTIVE."
    PRD §3.6: "Authorization prices the order but moves no inventory."

    Authorizing advances only the payment axis; fulfillment_status stays OPEN.

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_payment_and_fulfillment_axes
    """
    bq, cu, style, variant = setup_basic_retail_scenario(tax_rate_bps=875, list_price_cents=5000)
    order, _ = open_order_with_line(cu["id"], variant["id"], qty=1)
    assert order["payment_status"] == "UNPAID"
    assert order["fulfillment_status"] == "OPEN"

    authorized = validate_success(api.authorize_order(order["id"], ASSOCIATE), 200)
    assert authorized["payment_status"] == "AUTHORIZED"
    assert authorized["fulfillment_status"] == "OPEN", "fulfillment axis unchanged by authorize"


# ─── Queue B: state_machines ──────────────────────────────────────────────

def test_capture_unauthorized_order_rejected_invalid_state(api):
    """PRD §3.6: "Capturing an order (payment_status AUTHORIZED -> CAPTURED) settles
    cash, moves inventory, and mints loyalty. Capture is permitted only from
    AUTHORIZED".
    PRD §2.8: "the state check that the target resource is in a state from which the
    requested transition is defined (ERR_INVALID_STATE, HTTP 409)."

    Capturing an order still UNPAID (never authorized) returns ERR_INVALID_STATE.

    Design: Corner/state_machines/capture_unauthorized_order_returns_invalid_state
    """
    bq, cu, style, variant = setup_basic_retail_scenario(tax_rate_bps=0, list_price_cents=5000)
    order, _ = open_order_with_line(cu["id"], variant["id"], qty=1)
    assert order["payment_status"] == "UNPAID"

    res = api.capture_order(order["id"], ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_captured_order_rejected_invalid_state(api):
    """PRD §3.6: "Cancellation is forbidden once the order is CAPTURED — the
    from-state guard makes such an attempt an ERR_INVALID_STATE (HTTP 409)."

    Cancelling after payment_status==CAPTURED (fulfillment still OPEN) is rejected
    with ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_captured_order_rejected_invalid_state
    """
    bq, cu, style, variant = setup_basic_retail_scenario(tax_rate_bps=0, list_price_cents=5000)
    captured, _ = create_captured_order(cu["id"], variant["id"], qty=1)
    assert captured["payment_status"] == "CAPTURED"
    assert captured["fulfillment_status"] == "OPEN"

    res = api.cancel_order(captured["id"], ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Queue B: consistency_model ───────────────────────────────────────────

def test_capture_reflects_total_points_and_inventory_in_same_response(api):
    """PRD §2.4: the system applies operations under immediate consistency, returning
    the updated resource object in the data field.
    PRD §3.6: "The order's points_earned is the net-cash total divided by 100 and
    taken as the floor (the whole number of points, discarding any remainder), since
    one point is earned per 100 cents of net cash."
    PRD §3.6: "For each order line the variant's on_hand is decremented by qty,
    available is recomputed, and total_available is bubbled up to the style."

    An order priced 5000 + tax 875 -> total 5438; capture returns total_cents 5438
    and points_earned 54, and the variant drops to on_hand 4.

    Design: Corner/consistency_model/capture_reflects_inventory_and_points_in_same_response
    """
    bq, cu, style, variant = setup_basic_retail_scenario(tax_rate_bps=875, list_price_cents=5000)
    captured, line = create_captured_order(cu["id"], variant["id"], qty=1)
    assert captured["total_cents"] == 5438
    assert captured["points_earned"] == 54

    variant_after = get_success_data(api.get_sku_variant(variant["id"], ASSOCIATE))
    assert variant_after["on_hand"] == 4
