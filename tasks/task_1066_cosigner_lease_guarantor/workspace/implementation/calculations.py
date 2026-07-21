"""Calculation rules (PRD 3.1, 3.2, 3.4, 3.5, 3.6)."""
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    CREDIT_FLOOR, A_CREDIT, A_DTI, B_CREDIT, B_DTI, C_CREDIT, C_DTI,
    COVERED_FRACTION, MIN_FEE_CENTS, MAX_FEE_CENTS, TIER_RATE,
    TIER_WEIGHT, POSTURE_WARN_FRACTION,
)


def round_half_up_cents(value):
    """Round a Decimal to whole cents, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def debt_to_income(monthly_obligations_cents, annual_income_cents):
    """monthly_obligations / (annual_income / 12), rounded 4 dp half-up (PRD 3.1)."""
    ratio = (Decimal(monthly_obligations_cents) * 12) / Decimal(annual_income_cents)
    return ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def assign_risk_tier(credit_score, dti):
    """First-match tier ladder on the rounded dti (PRD 3.1). dti is a Decimal."""
    if credit_score >= A_CREDIT and dti <= A_DTI:
        return "A"
    if credit_score >= B_CREDIT and dti <= B_DTI:
        return "B"
    if credit_score >= C_CREDIT and dti <= C_DTI:
        return "C"
    return "D"


def per_month_coverage(monthly_rent_cents):
    """round_half_up(monthly_rent * 0.90) (PRD 3.2)."""
    return round_half_up_cents(Decimal(monthly_rent_cents) * COVERED_FRACTION)


def guarantee_fee(total_coverage_cents, term_months, tier):
    """base_rate * total_coverage * (term_months/12), rounded once, clamped (PRD 3.2/3.4)."""
    base_rate = TIER_RATE[tier]
    term_factor = Decimal(term_months) / Decimal(12)
    raw = base_rate * Decimal(total_coverage_cents) * term_factor
    fee = round_half_up_cents(raw)
    fee = max(MIN_FEE_CENTS, min(fee, MAX_FEE_CENTS))
    return fee


def rent_to_income_ratio(monthly_rent_cents, annual_income_cents):
    """monthly_rent / (annual_income / 12), full precision Decimal (PRD 3.4)."""
    return (Decimal(monthly_rent_cents) * 12) / Decimal(annual_income_cents)


def weighted(amount_cents, tier):
    """round_half_up(amount * TIER_WEIGHT[tier])."""
    return round_half_up_cents(Decimal(amount_cents) * TIER_WEIGHT[tier])


def risk_weighted_sum(pairs):
    """round_half_up(sum(amount * weight)) applied once after the whole sum (PRD 3.5)."""
    total = Decimal(0)
    for amount_cents, tier in pairs:
        total += Decimal(amount_cents) * TIER_WEIGHT[tier]
    return round_half_up_cents(total)


def warn_threshold(exposure_cap_cents):
    return round_half_up_cents(POSTURE_WARN_FRACTION * Decimal(exposure_cap_cents))
