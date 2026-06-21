"""Difficulty rule 2 — combinatorial / rounding-sensitive formulas (PRD §3.5).

Per-share round_half_up on the discounted purchase price.

NOTE: the sibling instance `accrual_cap_waterfall_min_of_cap_and_cash` is SKIPPED
(not emitted). Its setup recipe drives the participant's 2024 accrual to exactly the
$25k cap (gross 20,000,000c at 15% = 3,000,000c; cap-max = floor(2,500,000/1000) =
2500 shares => 2,500,000c accrued => remaining capacity 0), so the PRD §3.6 cap
allocation uniquely yields shares_purchased == 0 for the second batch — not the
instance's asserted shares_purchased == 1 / spend 850 / residual 99150 /
grant_date_value_applied 1000. The asserted literals are not uniquely derivable
from the PRD applied to that setup, so the instance is skipped per the PRD-first
two-condition filter.
"""
from test_helpers import (
    validate_success,
    setup_settled_purchase,
)


def test_per_share_price_rounds_half_up(api, admin_headers):
    """PRD §3.5: "The price_per_share_cents is then the applicable fair market value
    multiplied by the quantity (100 minus the plan's discount_pct), divided by 100,
    and rounded half up to the nearest whole cent."
    PRD §2.5: "The single point at which rounding occurs is the per-share discounted
    purchase price, which is rounded half up to the nearest whole cent."

    applicable_fmv 999c, discount 15 => 999*85/100 = 849.15 => round_half_up = 849.

    Design: Difficulty/combinatorial_formula/lookback_price_rounding_half_up_per_share
    """
    ctx = setup_settled_purchase(
        plan_overrides={"discount_pct": 15, "lookback_enabled": True},
        offering_overrides={"grant_date_fmv_cents": 999},
        batch_overrides={"purchase_date_fmv_cents": 1200},
    )
    purchase = validate_success(api.get_purchase(ctx["purchase"]["id"], admin_headers))
    assert purchase["price_per_share_cents"] == 849, purchase


def test_per_share_price_rounds_half_up_via_share_lot_consistency(api, admin_headers):
    """PRD §3.5: "The price_per_share_cents is then the applicable fair market value
    multiplied by the quantity (100 minus the plan's discount_pct), divided by 100,
    and rounded half up to the nearest whole cent."
    PRD §3.5: "the spend_cents actually drawn from contributions (the shares
    purchased multiplied by the price per share)".

    Second test of the same instance from a different angle: spend_cents must equal
    shares_purchased * the rounded 849c price, confirming the per-share rounding is
    applied before the multiply (not a sum-then-round).

    Design: Difficulty/combinatorial_formula/lookback_price_rounding_half_up_per_share
    """
    ctx = setup_settled_purchase(
        plan_overrides={"discount_pct": 15, "lookback_enabled": True},
        offering_overrides={"grant_date_fmv_cents": 999},
        batch_overrides={"purchase_date_fmv_cents": 1200},
    )
    purchase = validate_success(api.get_purchase(ctx["purchase"]["id"], admin_headers))
    assert purchase["price_per_share_cents"] == 849, purchase
    assert purchase["spend_cents"] == purchase["shares_purchased"] * 849, purchase
