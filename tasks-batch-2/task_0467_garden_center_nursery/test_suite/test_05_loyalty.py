"""Loyalty accrual variants, points conservation, and credit-hold lifting.

Difficulty: loyalty_accrual_standard_vs_gold_on_account, cancel_conserves_loyalty_points.
Corner: pay_on_account_order_lifts_credit_hold.
"""
from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_paginated,
    factories as F, fixtures as X,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INV = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["sales_clerk_headers"]


def _gold_threshold_20_setup():
    """Nursery (accrual 1/$, gold threshold 20), RETAIL account, DRY_GOOD @ 3000, released lot."""
    X.set_clock("2026-04-01T09:00:00Z")
    nursery = X.create_nursery(loyalty_accrual_per_dollar=1, gold_tier_threshold_points=20)
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-1", name="Trellis", unit_price_cents=3000)
    X.create_released_lot(product["id"], received_qty=50, unit_cost_cents=1000)
    return nursery, account, product


def _fulfill_one_unit(account_id, product_id, redeem=None):
    """Open an order with one unit, walk confirm->allocate->pay->fulfill. Returns fulfilled order."""
    order = X.create_order(account_id)
    X.add_line(order["id"], product_id, qty=1)
    overrides = {"requested_redeem_points": redeem} if redeem else {}
    c = X.confirm(order["id"], order["version"], **overrides)
    a = X.allocate(order["id"], c["version"])
    p = X.pay(order["id"], a["version"])
    return X.fulfill(order["id"], p["version"])


# ---------------------------------------------------------------------------
# Difficulty: loyalty_accrual_standard_vs_gold_on_account
# ---------------------------------------------------------------------------
def test_standard_accrual_then_account_becomes_gold(api):
    """PRD §3.5: "In the `STANDARD` variant, when the account's tier is `STANDARD`
    at fulfill time, the rate is the base rate with no multiplier."
    PRD §3.5: "an account is `GOLD` when its lifetime points are at or above
    `gold_tier_threshold_points`, and `STANDARD` otherwise."

    Design: Difficulty/dual_variant_calc/loyalty_accrual_standard_vs_gold_on_account
    """
    nursery, account, product = _gold_threshold_20_setup()
    _fulfill_one_unit(account["id"], product["id"])  # net 3000 -> 30 dollars -> 30 points STANDARD
    acc = validate_success(api.get_account(account["id"], CLERK))
    assert acc["lifetime_points"] == 30
    assert acc["loyalty_tier"] == "GOLD", "30 >= gold threshold 20"


def test_gold_accrual_doubles_points(api):
    """PRD §3.5: "In the `GOLD` variant, when the account's tier is `GOLD` at
    fulfill time, the rate is the base rate multiplied by the gold multiplier of 2,
    doubling the same net total into points."

    Design: Difficulty/dual_variant_calc/loyalty_accrual_standard_vs_gold_on_account
    """
    nursery, account, product = _gold_threshold_20_setup()
    _fulfill_one_unit(account["id"], product["id"])           # STANDARD -> 30, now GOLD
    _fulfill_one_unit(account["id"], product["id"])           # GOLD -> 60
    acc = validate_success(api.get_account(account["id"], CLERK))
    assert acc["lifetime_points"] == 90, "30 (STANDARD) + 60 (GOLD)"
    # The second accrual event carries the doubled delta.
    events, _ = validate_paginated(api.list_loyalty_events(account["id"], CLERK))
    accruals = [e for e in events if e["event_type"] == "ACCRUAL"]
    assert any(e["points_delta"] == 60 for e in accruals), "GOLD accrual delta == 60"


# ---------------------------------------------------------------------------
# Difficulty: cancel_conserves_loyalty_points
# ---------------------------------------------------------------------------
def _account_with_40_points_then_redeem_30():
    """Account seeded to 40 points via a fulfilled order, then order#2 confirmed
    redeeming 30 (balance -> 10). Returns (account_id, order2_id, order2_version)."""
    nursery = X.create_nursery(loyalty_accrual_per_dollar=1, gold_tier_threshold_points=100000)
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-12", name="Feeder", unit_price_cents=4000)
    X.create_released_lot(product["id"], received_qty=10, unit_cost_cents=1000)
    _fulfill_one_unit(account["id"], product["id"])  # net 4000 -> 40 points STANDARD
    order2 = X.create_order(account["id"])
    X.add_line(order2["id"], product["id"], qty=1)
    c = X.confirm(order2["id"], order2["version"], requested_redeem_points=30)
    return account["id"], order2["id"], c["version"]


def test_confirm_redemption_drops_points_balance(api):
    """PRD §3.3: "If the buyer asked to redeem any points, confirmation appends a
    loyalty redemption event whose points change is the negative of the requested
    points, then recomputes the account's redeemable balance accordingly."

    Design: Difficulty/compensating_invariant/cancel_conserves_loyalty_points
    """
    account_id, _o2, _v = _account_with_40_points_then_redeem_30()
    acc = validate_success(api.get_account(account_id, CLERK))
    assert acc["points_balance"] == 10, "40 earned - 30 redeemed"


def test_cancel_reverses_redemption_restoring_points(api):
    """PRD §3.4: "If a redemption event was posted at confirmation, a reversal event
    is appended whose points change is the positive of the redeemed points, and the
    account's redeemable balance is recomputed."

    Design: Difficulty/compensating_invariant/cancel_conserves_loyalty_points
    """
    account_id, order2_id, v = _account_with_40_points_then_redeem_30()
    validate_success(api.cancel_order(order2_id, F.version_payload(v), CLERK))
    acc = validate_success(api.get_account(account_id, CLERK))
    assert acc["points_balance"] == 40, "redemption reversed, restored with zero drift"


# ---------------------------------------------------------------------------
# Corner: pay_on_account_order_lifts_credit_hold
# ---------------------------------------------------------------------------
def test_pay_on_account_lifts_credit_hold(api):
    """PRD §3.6: "When that repayment brings the account's outstanding balance at or
    below its credit limit and the account is currently on `CREDIT_HOLD`, the
    account is restored to `ACTIVE` — the compensating counterpart to the
    credit-hold bubble-up."

    Design: Corner/cross_cutting_complexity_layers/pay_on_account_order_lifts_credit_hold
    """
    ctx = X.setup_b2b_credit_hold(credit_limit_cents=5000)
    before = validate_success(api.get_account(ctx["account"]["id"], CLERK))
    assert before["status"] == "CREDIT_HOLD"
    assert before["outstanding_balance_cents"] == 5000
    validate_success(api.pay_order(ctx["order"]["id"], F.version_payload(ctx["order_version"]), CLERK))
    after = validate_success(api.get_account(ctx["account"]["id"], CLERK))
    assert after["outstanding_balance_cents"] == 0
    assert after["status"] == "ACTIVE"
