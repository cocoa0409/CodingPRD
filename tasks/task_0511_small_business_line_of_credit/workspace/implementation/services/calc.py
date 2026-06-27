"""Calculation rules (SCAFFOLD §1.3, PRD §3).

All monetary amounts are integer cents. Rounding is round-half-up to whole cents
unless stated otherwise. We use decimal.Decimal for the rounding step to avoid
IEEE-754 drift (PRD §2.7). The weighted-blend intermediate sub-scores are kept at
full precision (per spec) using float, then the FINAL value is rounded once.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

import constants as C


def round_half_up(value):
    """Round a numeric value to a whole integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def underwriting_risk_score(*, avg_daily_balance_cents, nsf_count_90d, deposit_volume_cents,
                            monthly_revenue_cents, requested_limit_cents):
    """Weighted blend; sum-then-round-once. Returns integer 0..100.

    Component sub-scores are NOT individually rounded; only the final raw*100 is
    rounded once (0 dp, half-up).
    """
    balance_ratio = min(1.0, avg_daily_balance_cents / max(1, requested_limit_cents))
    revenue_ratio = min(1.0, deposit_volume_cents / max(1, monthly_revenue_cents * 3))
    nsf_penalty = min(1.0, nsf_count_90d * C.NSF_PENALTY_STEP)
    raw = (C.W_BALANCE * balance_ratio) + (C.W_REVENUE * revenue_ratio) - (C.W_NSF * nsf_penalty)
    raw = max(0.0, min(1.0, raw))
    return round_half_up(raw * 100)


def tier_for_score(score):
    """Threshold-selection of pricing tier. Returns 'TIER_A'|'TIER_B'|'TIER_C'|None.

    None means the score is below the approval floor (no tier eligible)."""
    if score >= C.TIER_A_FLOOR:
        return "TIER_A"
    if score >= C.TIER_B_FLOOR:
        return "TIER_B"
    if score >= C.APPROVAL_SCORE_FLOOR:
        return "TIER_C"
    return None


def approved_limit(*, requested_limit_cents, avg_daily_balance_cents, tier,
                   current_limit_cents=None):
    """Tiered advance cap.

    raw_cap = floor(avg_daily_balance_cents * advance_multiple)
    origination: approved = min(requested, raw_cap)
    increase   : approved = max(current_limit, min(requested, raw_cap))
    """
    advance_multiple = C.ADVANCE_MULTIPLE[tier]
    raw_cap = math.floor(avg_daily_balance_cents * advance_multiple)
    approved = min(requested_limit_cents, raw_cap)
    if current_limit_cents is not None:
        approved = max(current_limit_cents, approved)
    return approved


def draw_fee(*, principal_cents, fee_factor_bps):
    """Flat fee = round(principal * fee_factor_bps / 10000), half-up to whole cents."""
    return round_half_up(Decimal(principal_cents) * Decimal(fee_factor_bps) / Decimal(C.BPS_DENOMINATOR))


def renewal_total_fee(*, credit_limit_cents, new_fee_factor_bps):
    """round(credit_limit * new_fee_factor_bps / 10000), half-up to whole cents."""
    return round_half_up(Decimal(credit_limit_cents) * Decimal(new_fee_factor_bps) / Decimal(C.BPS_DENOMINATOR))


def equivalent_apr(*, new_fee_factor_bps, term_days):
    """Annualize-after-rate; single final round half-up to whole bps.

    flat_rate = new_fee_factor_bps / 10000
    annualized = flat_rate * (DAYS_PER_YEAR / term_days)
    equivalent_apr_bps = round(annualized * 10000)
    """
    flat_rate = new_fee_factor_bps / C.BPS_DENOMINATOR
    annualized = flat_rate * (C.DAYS_PER_YEAR / term_days)
    return round_half_up(annualized * C.BPS_DENOMINATOR)


def remittance_target(*, outstanding_total, cadence):
    """target_amount = round(outstanding_total * pct), half-up, BEFORE the min() cap."""
    pct = C.DAILY_REMIT_PCT if cadence == "DAILY" else C.WEEKLY_REMIT_PCT
    return round_half_up(Decimal(outstanding_total) * Decimal(str(pct)))
