"""Pure calculation functions (SCAFFOLD §1.3, PRD §3.4/§3.6/§3.7).

All monetary amounts are integer cents. Division rounding directions are pinned
exactly per the PRD at each point of use. No floats are used for money: the 0.05
and 0.10 bonus rates are applied as floor(value * 5 // 100) / floor(value * 10 // 100)
to stay in exact integer arithmetic.
"""
import math


def engagement_rate_bps(total_engagements, total_impressions):
    """engagement_rate (SCAFFOLD §1.3).

    if total_impressions == 0: 0
    else round_half_up(total_engagements * 10000 / total_impressions)
    multiply-before-divide is pinned to avoid truncation.
    """
    if total_impressions == 0:
        return 0
    numerator = total_engagements * 10000
    # round half up on a non-negative quotient
    return _round_half_up_div(numerator, total_impressions)


def _round_half_up_div(numerator, denominator):
    """Integer round-half-up of numerator/denominator (both non-negative)."""
    return (numerator * 2 + denominator) // (2 * denominator)


def collab_settlement_amount_cents(offer_fee_cents, deliverable_count, approved_asset_count):
    """collab_settlement_amount (SCAFFOLD §1.3, PRD §3.6).

    base = offer_fee_cents
    per_deliverable_value = floor(base / deliverable_count)
    tier2_units = max(0, min(approved_asset_count, 5) - 2)   # 5% rate
    tier3_units = max(0, approved_asset_count - 5)            # 10% rate
    bonus = floor(per_deliverable_value*0.05)*tier2_units
          + floor(per_deliverable_value*0.10)*tier3_units
    floor per line item THEN multiply by unit count THEN sum.
    """
    base = offer_fee_cents
    per_deliverable_value = base // deliverable_count
    tier2_units = max(0, min(approved_asset_count, 5) - 2)
    tier3_units = max(0, approved_asset_count - 5)
    # floor(per_deliverable_value * 0.05) == floor(per_deliverable_value * 5 / 100)
    five_pct_unit = (per_deliverable_value * 5) // 100
    ten_pct_unit = (per_deliverable_value * 10) // 100
    bonus = five_pct_unit * tier2_units + ten_pct_unit * tier3_units
    return base + bonus


def boost_billable_final(spent_budget_cents, daily_cap_cents, days_elapsed, reserved_budget_cents):
    """boost_settlement_cost final_spent variant (SCAFFOLD §1.3, PRD §3.4).

    billable = min(spent_budget_cents,
                   daily_cap_cents * days_elapsed,
                   reserved_budget_cents)
    """
    return min(
        spent_budget_cents,
        daily_cap_cents * days_elapsed,
        reserved_budget_cents,
    )


def retainer_churn_quote(retainer_fee_cents, posts_published_this_cycle, monthly_post_quota):
    """retainer_proration_on_churn (SCAFFOLD §1.3, PRD §3.7).

    forward_full = retainer_fee_cents
    chronological_prorated =
        0 if posts_published_this_cycle == 0
        else ceil(retainer_fee_cents * posts_published_this_cycle / monthly_post_quota)
    monthly_post_quota guaranteed >= 1.
    """
    forward_full = retainer_fee_cents
    if posts_published_this_cycle == 0:
        prorated = 0
    else:
        prorated = math.ceil(
            (retainer_fee_cents * posts_published_this_cycle) / monthly_post_quota
        )
    return forward_full, prorated
