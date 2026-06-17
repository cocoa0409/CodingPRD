"""Order parallel dimensions, payment/fulfillment, payments log, invoice read, OCC pay.

Each test translates exactly one design-index instance. Difficulty instances each
receive at least two tests.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_seller_headers, make_buyer_headers,
    register_seller, register_buyer,
    set_clock,
    setup_bought_order, setup_paid_order,
    buy_now_order, pay_order, ship_order,
    setup_published_buy_now,
)

ANON = TEST_USERS["anonymous_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ════════════════════════════════════════════════════════════════════
# Difficulty: order_parallel_payment_fulfillment_dimensions (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_pay_then_ship_advances_dimensions_independently(api):
    """PRD §3.8: "Paying appends a Payment event of kind CHARGE whose amount_cents equals
    the order's total_cents, sets paid_amount_cents to total_cents, moves payment_status to
    PAID, and — bubbling across into the fulfillment dimension — moves fulfillment_status
    from AWAITING_PAYMENT to READY_TO_SHIP."
    PRD §3.8: "shipping moves fulfillment_status to SHIPPED and increments the order's
    version by one."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
    """
    seller, buyer, listing, order = setup_bought_order(
        buy_now_price_cents=20000, shipping_cents=500)
    order = pay_order(order, buyer["id"])
    order = ship_order(order["id"], seller["id"])

    assert order["payment_status"] == "PAID"
    assert order["fulfillment_status"] == "SHIPPED"
    assert order["paid_amount_cents"] == 20500


def test_pay_bubbles_fulfillment_to_ready_to_ship(api):
    """PRD §3.8: "Paying appends a Payment event of kind CHARGE whose amount_cents equals
    the order's total_cents, sets paid_amount_cents to total_cents, moves payment_status to
    PAID, and — bubbling across into the fulfillment dimension — moves fulfillment_status
    from AWAITING_PAYMENT to READY_TO_SHIP."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
    """
    seller, buyer, listing, order = setup_bought_order(
        buy_now_price_cents=20000, shipping_cents=0)
    assert order["payment_status"] == "UNPAID"
    assert order["fulfillment_status"] == "AWAITING_PAYMENT"

    order = pay_order(order, buyer["id"])
    assert order["payment_status"] == "PAID"
    assert order["fulfillment_status"] == "READY_TO_SHIP"
    assert order["paid_amount_cents"] == 20000


# ════════════════════════════════════════════════════════════════════
# Difficulty: ship_requires_order_payment_paid (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_ship_unpaid_order_rejected_invalid_state(api):
    """PRD §3.8: "A seller marks the order shipped, which is permitted only when the
    payment_status is PAID and the fulfillment_status is READY_TO_SHIP"
    PRD §3.5 / §5: a transition from a state in which it is not defined is refused with
    ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/ship_requires_order_payment_paid
    """
    seller, buyer, listing, order = setup_bought_order(
        buy_now_price_cents=20000, shipping_cents=0)
    res = api.ship_order(order["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_order(order["id"], make_seller_headers(seller["id"])), 200)
    assert after["fulfillment_status"] == "AWAITING_PAYMENT"
    assert after["payment_status"] == "UNPAID"


def test_ship_succeeds_only_after_payment(api):
    """PRD §3.8: "A seller marks the order shipped, which is permitted only when the
    payment_status is PAID and the fulfillment_status is READY_TO_SHIP; shipping moves
    fulfillment_status to SHIPPED and increments the order's version by one."

    Design: Difficulty/cross_entity_state_dependency/ship_requires_order_payment_paid
    """
    seller, buyer, listing, order = setup_paid_order(
        buy_now_price_cents=20000, shipping_cents=0)
    shipped = validate_success(
        api.ship_order(order["id"], make_seller_headers(seller["id"])), 200)
    assert shipped["fulfillment_status"] == "SHIPPED"
    assert shipped["payment_status"] == "PAID"


# ════════════════════════════════════════════════════════════════════
# Corner: get_order_invoice_computed_read
# ════════════════════════════════════════════════════════════════════

def test_get_order_invoice_amount_matches_fee(api):
    """PRD §3.7: "For each tier, the exact product of that tier's slice in cents and its
    rate divided by ten thousand is computed; the rounding order is pinned to sum-then-round,
    meaning all of the exact tier products are summed first and only the resulting total is
    rounded half-up to a whole number of cents — never rounded tier by tier. The flat
    insertion fee of 30 cents is then added to that rounded value."

    Design: Corner/endpoints/get_order_invoice_computed_read
    """
    # Item 20000: tier1 slice 20000 * 0.1255 = 2510.0 exact; sum-then-round = 2510 + 30 = 2540.
    seller, buyer, listing, order = setup_bought_order(
        buy_now_price_cents=20000, shipping_cents=0)
    res = api.get_order_invoice(order["id"], make_seller_headers(seller["id"]))
    invoice = validate_success(res, 200)
    assert invoice["amount_cents"] == 2540


# ════════════════════════════════════════════════════════════════════
# Corner: order_payments_event_log_records_charge
# ════════════════════════════════════════════════════════════════════

def test_order_payments_log_records_charge(api):
    """PRD §3.8: "The paid_amount_cents field is the running sum of all CHARGE event amounts
    minus all REFUND event amounts and is a conserved-quantity anchor for the refund
    invariant. Each Payment is an append-only event whose amount_cents is at least 1 cent; a
    CHARGE adds to and a REFUND subtracts from paid_amount_cents."

    Design: Corner/endpoints/order_payments_event_log_records_charge
    """
    seller, buyer, listing, order = setup_bought_order(
        buy_now_price_cents=20000, shipping_cents=500)
    order = pay_order(order, buyer["id"])

    res = api.list_order_payments(order["id"], make_buyer_headers(buyer["id"]))
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert data[0]["kind"] == "CHARGE"
    assert data[0]["amount_cents"] == 20500

    after = validate_success(api.get_order(order["id"], make_buyer_headers(buyer["id"])), 200)
    assert after["paid_amount_cents"] == 20500


# ════════════════════════════════════════════════════════════════════
# Corner: dispute_on_unpaid_order_rejected
# ════════════════════════════════════════════════════════════════════

def test_dispute_on_unpaid_order_rejected(api):
    """PRD §3.10: "Opening a dispute requires the order's payment_status to be PAID, requires
    the requested_amount_cents to be at least 1 and at most the order's paid_amount_cents,
    and allows only one OPEN dispute per order; a violation of any of these is refused with
    ERR_DISPUTE_NOT_ELIGIBLE."

    Design: Corner/validations/dispute_on_unpaid_order_rejected
    """
    seller, buyer, listing, order = setup_bought_order(
        buy_now_price_cents=20000, shipping_cents=0)
    res = api.create_dispute(order["id"],
                             {"opener_account_id": buyer["id"],
                              "reason": "ITEM_NOT_RECEIVED",
                              "requested_amount_cents": 1000},
                             make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_DISPUTE_NOT_ELIGIBLE", expected_status=422)


# ════════════════════════════════════════════════════════════════════
# Corner: occ_order_pay_stale_version
# ════════════════════════════════════════════════════════════════════

def test_order_pay_stale_version_rejected(api):
    """PRD §2.9: "If a cascaded side effect — such as the seller cancelling the unpaid order,
    or a fee recompute — has advanced the order's version since the buyer's checkout view was
    loaded, the submitted expected_order_version will not match the order's current version,
    and the payment is rejected with ERR_STALE_VERSION (HTTP 412) rather than being applied
    against an obsolete total."

    Design: Corner/cross_cutting_complexity_layers/occ_order_pay_stale_version
    """
    seller, buyer, listing, order = setup_bought_order(
        buy_now_price_cents=20000, shipping_cents=0)
    stale_version = order["version"]
    # Seller cancels the unpaid order, advancing the order version.
    validate_success(api.cancel_order(order["id"], make_seller_headers(seller["id"])), 200)

    res = api.pay_order(order["id"], {"expected_order_version": stale_version},
                        make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# ════════════════════════════════════════════════════════════════════
# Corner: buy_now_response_reflects_order_immediately
# ════════════════════════════════════════════════════════════════════

def test_buy_now_response_reflects_order_immediately(api):
    """PRD §3.6: "The order's total_cents is computed as the sum of item_price_cents and
    shipping_cents."
    PRD §3.6: "snapshots the agreed item_price_cents (the winning bid amount, the buy-now
    price, or the accepted offer amount, respectively)."

    Design: Corner/consistency_model/buy_now_response_reflects_order_immediately
    """
    seller, buyer, listing = setup_published_buy_now(buy_now_price_cents=20000)
    res = api.buy_now(listing["id"],
                      {"buyer_account_id": buyer["id"], "shipping_cents": 500},
                      make_buyer_headers(buyer["id"]))
    order = validate_success(res, 201)
    assert order["total_cents"] == 20500
    assert order["item_price_cents"] == 20000
    assert order["source"] == "BUY_NOW"
