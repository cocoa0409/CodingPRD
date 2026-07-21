"""Returns and exchanges: the approve settlement + loyalty-clawback cascade,
return-state gates, completed-order gate, and the return window.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_shopper_headers,
    set_clock,
    setup_buyable,
    setup_completed_buy_order,
    place_order,
    request_return,
    approve_return,
    reject_return,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["fulfillment_agent_headers"]


def _read_customer(api, customer_id):
    return validate_success(api.get_customer(customer_id, ADMIN), 200)


# ---- transitive_cascade: return_approve_clawback_depth3 ----

def test_return_approve_refund_and_clawback(api):
    """PRD §3.8: "The `restocking_fee_cents` withheld is the order's
    `subtotal_cents` times a restocking rate of 10 percent (0.10), rounded half
    up, but only for a `REFUND`."
    PRD §3.8: "The `refund_cents` is the order's `grand_total_cents` minus that
    restocking fee, floored at zero."
    PRD §3.8: "The linked order's `payment_status` is set to `REFUNDED`. The
    loyalty points the order had earned are clawed back: the customer's
    `lifetime_points` is reduced by the order's `earned_points`, her
    `loyalty_points` is reduced by the same amount but never below zero."

    Design: Difficulty/transitive_cascade/return_approve_clawback_depth3
    """
    base = setup_completed_buy_order(api, buy_price_cents=10000, category="POSTPARTUM")
    cust_id = base["customer"]["id"]
    before = _read_customer(api, cust_id)
    assert before["lifetime_points"] == 100  # floor((10000-0)/100) granted at fulfill

    ret = request_return(api, base["order"]["id"], cust_id, return_type="REFUND")
    approved = approve_return(api, ret["id"])
    assert approved["status"] == "APPROVED"
    assert approved["restocking_fee_cents"] == 1000  # round(10000 * 0.10)
    assert approved["refund_cents"] == 9000          # 10000 - 1000

    order = validate_success(api.get_order(base["order"]["id"], AGENT), 200)
    assert order["payment_status"] == "REFUNDED"
    after = _read_customer(api, cust_id)
    assert after["lifetime_points"] == 0
    assert after["loyalty_points"] == 0


def test_return_approve_clawback_larger_order(api):
    """PRD §3.8: "the customer's `lifetime_points` is reduced by the order's
    `earned_points`, her `loyalty_points` is reduced by the same amount but never
    below zero, a `LoyaltyLedger` entry with reason `CLAWBACK_EARNED` is
    appended, and her `loyalty_tier` is recomputed from the reduced lifetime
    figure."
    PRD §3.8: "The `refund_cents` is the order's `grand_total_cents` minus that
    restocking fee, floored at zero."

    Design: Difficulty/transitive_cascade/return_approve_clawback_depth3
    """
    base = setup_completed_buy_order(api, buy_price_cents=20000, category="POSTPARTUM")
    cust_id = base["customer"]["id"]
    before = _read_customer(api, cust_id)
    assert before["lifetime_points"] == 200  # floor(20000/100)

    ret = request_return(api, base["order"]["id"], cust_id, return_type="REFUND")
    approved = approve_return(api, ret["id"])
    assert approved["restocking_fee_cents"] == 2000  # round(20000 * 0.10)
    assert approved["refund_cents"] == 18000         # 20000 - 2000
    after = _read_customer(api, cust_id)
    assert after["lifetime_points"] == 0
    assert after["loyalty_points"] == 0


# ---- Corner: approve_rejected_return_rejected ----

def test_approve_already_rejected_return_rejected(api):
    """PRD §3.8: "A fulfillment agent resolves a return by approving or rejecting
    it, in either case only while it is still `REQUESTED`; acting on a return
    that is not requested is rejected with `ERR_RETURN_NOT_REQUESTED`."

    Design: Corner/state_machines/approve_rejected_return_rejected
    """
    base = setup_completed_buy_order(api, buy_price_cents=6000, category="POSTPARTUM")
    ret = request_return(api, base["order"]["id"], base["customer"]["id"],
                         return_type="REFUND", reason="changed mind")
    reject_return(api, ret["id"])
    resp = api.approve_return(ret["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_REQUESTED.value)


# ---- Corner: return_on_uncompleted_order_rejected ----

def test_return_on_uncompleted_order_rejected(api):
    """PRD §3.8: "A return may only be raised on an order that is COMPLETED — both
    `PAID` and `FULFILLED` — and a request against any order that is not
    completed is rejected with `ERR_ORDER_NOT_RETURNABLE`."

    Design: Corner/state_machines/return_on_uncompleted_order_rejected
    """
    base = setup_buyable(api, buy_price_cents=5000, inventory_on_hand=5, category="NURSING")
    order = place_order(api, base["customer"]["id"], base["variant"]["id"], "BUY", quantity=1)
    resp = api.create_return(
        {"order_id": order["id"], "reason": "x", "return_type": "REFUND"},
        make_shopper_headers(base["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_RETURNABLE.value)


# ---- Corner: return_window_expired_rejected ----

def test_return_window_expired_rejected(api):
    """PRD §3.8: "The request must also be timely: it must arrive within 30 days
    of the order's fulfillment, and a request made more than 30 days after
    fulfillment is rejected with `ERR_RETURN_WINDOW_EXPIRED`."

    Design: Corner/validations/return_window_expired_rejected
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    base = setup_completed_buy_order(api, buy_price_cents=5000, category="POSTPARTUM")
    set_clock(api, "2026-08-20T00:00:00Z")  # 50 days after fulfillment
    resp = api.create_return(
        {"order_id": base["order"]["id"], "reason": "too late", "return_type": "REFUND"},
        make_shopper_headers(base["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED.value)
