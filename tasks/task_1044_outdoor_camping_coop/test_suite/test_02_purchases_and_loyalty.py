"""Retail purchases: per-line tax rounding, loyalty earn/redeem, refund conservation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures, assert_loyalty_balance_conserved,
)

ADMIN = fixtures.ADMIN
STAFF = fixtures.STAFF


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula / purchase_per_line_tax_rounding_mode_b
# ---------------------------------------------------------------------------

def test_purchase_tax_rounded_per_line_then_summed(api):
    """PRD §3.2: "for each line, the line's tax is the line subtotal multiplied
    by that line's product `tax_rate`, rounded half-up to a whole cent;
    `tax_cents` is the sum of those per-line rounded taxes. Rounding the tax per
    line and then summing is the pinned discipline; summing the untaxed line
    amounts and rounding once at the end is explicitly not used."

    Design: Difficulty/combinatorial_formula/purchase_per_line_tax_rounding_mode_b
    """
    member, _ = fixtures.create_active_member(api)
    product = fixtures.create_product(api, retail_price_cents=1005, tax_rate=0.05)
    purchase = validate_success(api.create_purchase({
        "member_id": member["id"],
        "line_items": [
            {"product_id": product["id"], "quantity": 1, "unit_price_cents": 1005},
            {"product_id": product["id"], "quantity": 1, "unit_price_cents": 1005},
        ],
    }, STAFF), 201)
    assert purchase["subtotal_cents"] == 2010
    assert purchase["tax_cents"] == 100


def test_purchase_total_is_subtotal_plus_tax_minus_redemption(api):
    """PRD §3.2: "The `total_cents` charged is `subtotal_cents` plus `tax_cents`
    minus `loyalty_redemption_cents`."

    Design: Difficulty/combinatorial_formula/purchase_per_line_tax_rounding_mode_b
    """
    member, _ = fixtures.create_active_member(api)
    product = fixtures.create_product(api, retail_price_cents=1005, tax_rate=0.05)
    purchase = validate_success(api.create_purchase({
        "member_id": member["id"],
        "line_items": [
            {"product_id": product["id"], "quantity": 1, "unit_price_cents": 1005},
            {"product_id": product["id"], "quantity": 1, "unit_price_cents": 1005},
        ],
    }, STAFF), 201)
    assert purchase["total_cents"] == 2110


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant / loyalty_points_conserved_on_purchase_refund
# ---------------------------------------------------------------------------

def _setup_refundable_second_purchase(api):
    """Member with P1 (100000 -> earn 1000), then P2 (20000, redeem 500 -> balance 700)."""
    member, member_headers = fixtures.create_active_member(api)
    product = fixtures.create_product(api, retail_price_cents=100000, tax_rate=0.05)
    fixtures.create_purchase(
        api, member["id"],
        [{"product_id": product["id"], "quantity": 1, "unit_price_cents": 100000}])
    p2 = fixtures.create_purchase(
        api, member["id"],
        [{"product_id": product["id"], "quantity": 1, "unit_price_cents": 20000}],
        points_redeemed=500)
    return member, member_headers, p2


def test_purchase_refund_restores_loyalty_balance(api):
    """PRD §3.2: "A refund reverses the loyalty effects: it appends a reversal
    entry removing the `loyalty_points_earned` that the sale granted, and, if the
    sale had redeemed points, a second reversal entry restoring the redeemed
    amount."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_on_purchase_refund
    """
    member, member_headers, p2 = _setup_refundable_second_purchase(api)
    validate_success(api.refund_purchase(p2["id"], STAFF))
    member = validate_success(api.get_member(member["id"], member_headers))
    assert member["loyalty_points_balance"] == 1000


def test_loyalty_balance_equals_ledger_sum_after_refund(api):
    """PRD §3.2: "A member's `loyalty_points_balance` is always exactly the sum
    of that member's ledger deltas."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_on_purchase_refund
    """
    member, member_headers, p2 = _setup_refundable_second_purchase(api)
    validate_success(api.refund_purchase(p2["id"], STAFF))
    member = validate_success(api.get_member(member["id"], member_headers))
    entries, _ = validate_paginated(
        api.get_member_loyalty_ledger(member["id"], member_headers, params={"limit": 100}))
    assert_loyalty_balance_conserved(member, entries)


# ---------------------------------------------------------------------------
# Queue B — errors / purchase_insufficient_points_returns_402
# ---------------------------------------------------------------------------

def test_purchase_redeeming_more_points_than_held_rejected(api):
    """PRD §3.2: "A member must actually hold enough points to cover
    `points_redeemed`, otherwise the sale is rejected with
    `ERR_INSUFFICIENT_POINTS` (HTTP 402)."

    Design: Corner/errors/purchase_insufficient_points_returns_402
    """
    member, _ = fixtures.create_active_member(api)
    product = fixtures.create_product(api, retail_price_cents=5000, tax_rate=0.05)
    validate_error(api.create_purchase({
        "member_id": member["id"],
        "line_items": [{"product_id": product["id"], "quantity": 1, "unit_price_cents": 5000}],
        "points_redeemed": 100,
    }, STAFF), ApiErrorId.ERR_INSUFFICIENT_POINTS.value)
