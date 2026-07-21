"""Sales-order pricing (round-per-line-then-sum), the two independent payment /
fulfillment axes, and the order-return ledger reversal.

Queue-A depth: combinatorial_formula (order), non_linear_state_machine (parallel
axes), transitive_cascade (order return reverses member ledger). Queue-B: loyalty
floor, return-before-pay, immediate read-after-write.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    new_member, new_gear_sku, create_order, pay_order, fulfill_order,
    return_order, setup_paid_fulfilled_order, make_member_headers,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ─── combinatorial_formula / order_total_round_per_line_then_sum_mode_b ────

def _premier_two_line_order():
    member = new_member(tier="PREMIER")
    sku_a = new_gear_sku(name="Trail Socks A", category="APPAREL", price_cents=1025)
    sku_b = new_gear_sku(name="Trail Socks B", category="APPAREL", price_cents=1025)
    order = create_order(member, [(sku_a["id"], 1), (sku_b["id"], 1)])
    return member, order


def test_order_round_per_line_discount(api):
    """PRD §3.3: "The discount_cents is computed per line and rounded per line before
    summing: for each line, multiply its line gross by the member's tier rate (zero
    percent for BASIC, ten percent for PREMIER), round that line's discount to whole
    cents, and only then sum the rounded per-line discounts."

    Two PREMIER lines of 1025: round(102.5)=103 per line -> discount 206 (not 205).

    Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum_mode_b
    """
    _member, order = _premier_two_line_order()
    assert order["subtotal_cents"] == 2050
    assert order["discount_cents"] == 206


def test_order_total_and_loyalty(api):
    """PRD §3.3: "The order total_cents is the subtotal minus the summed discount.
    The loyalty_points_earned on the order is the total divided by one hundred,
    rounded down to a whole number."

    total 2050-206=1844; loyalty floor(1844/100)=18.

    Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum_mode_b
    """
    _member, order = _premier_two_line_order()
    assert order["total_cents"] == 1844
    assert order["loyalty_points_earned"] == 18


# ─── non_linear_state_machine / sales_order_parallel_payment_fulfillment_axes

def _unpaid_order():
    member = new_member()
    sku = new_gear_sku(name="Camp Stove", category="STOVE", price_cents=5000)
    order = create_order(member, [(sku["id"], 1)])
    return member, order


def test_fulfill_before_pay_keeps_payment_unpaid(api):
    """PRD §3.3: "Fulfilling an order is a staff operation on the fulfillment axis
    alone: it is allowed only while fulfillment_status is UNFULFILLED, moves that
    axis to FULFILLED, and touches no ledger because the two axes evolve
    independently."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_payment_fulfillment_axes
    """
    _member, order = _unpaid_order()
    fulfilled = fulfill_order(order["id"])
    assert fulfilled["fulfillment_status"] == "FULFILLED"
    assert fulfilled["payment_status"] == "UNPAID"


def test_pay_after_fulfill_independent_axes(api):
    """PRD §3.3: "A sales order tracks two independent state axes at once: a payment
    axis in payment_status moving through UNPAID, PAID, and REFUNDED, and a
    fulfillment axis in fulfillment_status moving through UNFULFILLED, FULFILLED, and
    RETURNED."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_payment_fulfillment_axes
    """
    member, order = _unpaid_order()
    fulfill_order(order["id"])
    paid = pay_order(member, order["id"])
    assert paid["payment_status"] == "PAID"
    assert paid["fulfillment_status"] == "FULFILLED"


# ─── transitive_cascade / order_return_reverses_member_ledger ──────────────

def test_order_return_sets_terminal_axes(api):
    """PRD §3.3: "On success payment_status becomes REFUNDED and fulfillment_status
    becomes RETURNED; the member's store_credit_cents increases by total_cents as a
    wallet refund; loyalty_points_balance decreases by loyalty_points_earned; and
    lifetime_eligible_spend_cents decreases by total_cents."

    Design: Difficulty/transitive_cascade/order_return_reverses_member_ledger
    """
    member, order = setup_paid_fulfilled_order(tier="PREMIER", credit=5000,
                                               sku_prices=(1025, 1025))
    returned = return_order(member, order["id"])
    assert returned["payment_status"] == "REFUNDED"
    assert returned["fulfillment_status"] == "RETURNED"


def test_order_return_reverses_wallet_and_loyalty(api):
    """PRD §3.3: "On success payment_status becomes REFUNDED and fulfillment_status
    becomes RETURNED; the member's store_credit_cents increases by total_cents as a
    wallet refund; loyalty_points_balance decreases by loyalty_points_earned; and
    lifetime_eligible_spend_cents decreases by total_cents."

    Started with 5000 credit; paid 1844 with credit; return restores 5000, loyalty 0,
    lifetime 0.

    Design: Difficulty/transitive_cascade/order_return_reverses_member_ledger
    """
    member, order = setup_paid_fulfilled_order(tier="PREMIER", credit=5000,
                                               sku_prices=(1025, 1025))
    return_order(member, order["id"])
    m = validate_success(api.get_member(member["id"], STAFF), 200)
    assert m["store_credit_cents"] == 5000
    assert m["loyalty_points_balance"] == 0
    assert m["lifetime_eligible_spend_cents"] == 0


# ─── Queue-B calculations / order_loyalty_points_floor_on_pay ──────────────

def test_order_loyalty_points_floor_on_pay(api):
    """PRD §3.3: "On success the payment axis moves to PAID; if use_store_credit is
    set the total_cents is deducted from store_credit_cents; the member's
    loyalty_points_balance increases by loyalty_points_earned; and
    lifetime_eligible_spend_cents increases by total_cents."

    BASIC order of 1850: loyalty floor(1850/100)=18, credited on pay.

    Design: Corner/calculations/order_loyalty_points_floor_on_pay
    """
    member = new_member()
    sku = new_gear_sku(name="Headlamp", category="APPAREL", price_cents=1850)
    order = create_order(member, [(sku["id"], 1)])
    assert order["loyalty_points_earned"] == 18
    pay_order(member, order["id"])
    m = validate_success(api.get_member(member["id"], STAFF), 200)
    assert m["loyalty_points_balance"] == 18


# ─── Queue-B state_machines / order_return_before_pay_returns_order_not_paid

def test_order_return_before_pay_returns_order_not_paid(api):
    """PRD §3.3: "It requires payment_status to be PAID and fulfillment_status to be
    FULFILLED; if either precondition is unmet the return is rejected with
    ERR_ORDER_NOT_PAID."

    Design: Corner/state_machines/order_return_before_pay_returns_order_not_paid
    """
    member, order = _unpaid_order()
    res = api.return_order(order["id"], make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_PAID.value)


# ─── Queue-B consistency_model / immediate_read_after_write_reflects_state ─

def test_immediate_read_after_pay_reflects_paid(api):
    """PRD §3.3: "Paying an order, available to the member or to staff, is allowed
    only while payment_status is UNPAID. ... On success the payment axis moves to
    PAID".

    Design: Corner/consistency_model/immediate_read_after_write_reflects_state
    """
    member, order = _unpaid_order()
    pay_order(member, order["id"])
    fetched = validate_success(
        api.get_order(order["id"], make_member_headers(member["id"])), 200)
    assert fetched["payment_status"] == "PAID"
