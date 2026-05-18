"""Pure calculation rules — see SCAFFOLD §1.3 calculations table.

All monetary values are integer cents. Decimal is used for precision-sensitive
arithmetic. Floats are only used in loan_monthly_payment where the formula
itself involves powers and ratios; the result is rounded once at the end.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

from config import (
    APR_UPLIFT_BPS,
    DISPOSITION_FEE_CENTS,
    GAP_PREMIUM_BPS,
    LEASE_MIN_DP_BPS,
    LEASE_TAX_BPS,
    LOAN_MIN_DP_BPS,
    PENALTY_PER_MILE_CENTS,
    PREPAYMENT_PENALTY_BPS,
    PURCHASE_OPTION_FEE_CENTS,
    TIER_1,
    TIER_1_MIN,
    TIER_2,
    TIER_2_MIN,
    TIER_3,
    TIER_3_MIN,
    TIER_4,
    TIER_4_MIN,
    TIER_5_DECLINED,
    TIER_APR_BPS,
    TIER_MONEY_FACTOR_MICRO,
)
from utils import ceil_int, floor_int, round_half_up_6dp


# ── FICO tier ───────────────────────────────────────────────────────────────


def derive_fico_tier(fico_score: int) -> str:
    """SCAFFOLD §1.3 fico_tier_assignment — inclusive lower thresholds."""
    if fico_score >= TIER_1_MIN:
        return TIER_1
    if fico_score >= TIER_2_MIN:
        return TIER_2
    if fico_score >= TIER_3_MIN:
        return TIER_3
    if fico_score >= TIER_4_MIN:
        return TIER_4
    return TIER_5_DECLINED


# ── Down payment minimums ───────────────────────────────────────────────────


def minimum_down_payment_loan_cents(msrp_cents: int, tier: str) -> int:
    """ceil(msrp_cents * tier_bps / 10000)."""
    bps = LOAN_MIN_DP_BPS.get(tier)
    if bps is None:
        # TIER_5_DECLINED never reaches this check; defensive.
        return 0
    d = Decimal(msrp_cents) * Decimal(bps) / Decimal(10000)
    return int(d.to_integral_value(rounding=ROUND_CEILING))


def minimum_down_payment_lease_cents(msrp_cents: int, tier: str) -> int:
    bps = LEASE_MIN_DP_BPS.get(tier)
    if bps is None:
        # TIER_4 / TIER_5_DECLINED never reach this check.
        return 0
    d = Decimal(msrp_cents) * Decimal(bps) / Decimal(10000)
    return int(d.to_integral_value(rounding=ROUND_CEILING))


# ── Tier APR / money factor ────────────────────────────────────────────────


def tier_apr_bps(tier: str) -> int:
    return TIER_APR_BPS[tier]


def tier_money_factor_micro(tier: str) -> int:
    return TIER_MONEY_FACTOR_MICRO[tier]


# ── Loan monthly payment ───────────────────────────────────────────────────


def loan_monthly_payment_cents(principal_cents: int, apr_bps: int, term_months: int) -> int:
    """Standard amortization formula with ceil at the end.

    M = ceil(P * r * (1+r)^n / ((1+r)^n - 1))
    where r = (apr_bps / 10000) / 12 and n = term_months.

    When r == 0, M = ceil(P / n). Intermediate float math is used for the
    power/ratio; the result is rounded once at the end (PRD §3.3, §2.8).
    """
    P = principal_cents
    n = term_months
    if apr_bps == 0:
        # Use ceiling division to avoid float drift.
        return -(-P // n)
    # Use Decimal for the rate-and-power computation for precision.
    r = (Decimal(apr_bps) / Decimal(10000)) / Decimal(12)
    one_plus_r_pow_n = (Decimal(1) + r) ** n
    numerator = Decimal(P) * r * one_plus_r_pow_n
    denominator = one_plus_r_pow_n - Decimal(1)
    monthly = numerator / denominator
    return int(monthly.to_integral_value(rounding=ROUND_CEILING))


# ── Lease monthly payment ──────────────────────────────────────────────────


def lease_monthly_payment_cents(
    capitalized_cost_cents: int,
    residual_value_cents: int,
    money_factor_micro: int,
    term_months: int,
) -> int:
    """Per-component round-then-sum order — SCAFFOLD §1.3 lease_monthly_payment.

      depreciation = floor((cap - residual) / term_months)
      finance      = floor((cap + residual) * money_factor_micro / 1_000_000)
      base         = depreciation + finance
      tax          = ceil(base * LEASE_TAX_BPS / 10000)
      monthly      = base + tax
    """
    dep = (capitalized_cost_cents - residual_value_cents) // term_months  # floor for non-negative
    # Use Decimal for finance and tax to avoid float drift on edge cases.
    fin_d = Decimal(capitalized_cost_cents + residual_value_cents) * Decimal(money_factor_micro) / Decimal(1_000_000)
    fin = int(fin_d.to_integral_value(rounding=ROUND_FLOOR))
    base = dep + fin
    tax_d = Decimal(base) * Decimal(LEASE_TAX_BPS) / Decimal(10000)
    tax = int(tax_d.to_integral_value(rounding=ROUND_CEILING))
    return base + tax


# ── Residual value ─────────────────────────────────────────────────────────


def residual_value_cents(msrp_cents: int, residual_factor_bps: int) -> int:
    """floor(msrp_cents * residual_factor_bps / 10000)."""
    d = Decimal(msrp_cents) * Decimal(residual_factor_bps) / Decimal(10000)
    return int(d.to_integral_value(rounding=ROUND_FLOOR))


# ── Amortization step ──────────────────────────────────────────────────────


def amortization_step(remaining_principal_cents: int, amount_due_cents: int, apr_bps: int):
    """Split a LOAN payment into interest and principal.

      r              = (apr_bps / 10000) / 12
      interest_part  = floor(remaining_principal_cents * r)
      principal_part = amount_due_cents - interest_part
      trim principal_part to remaining_principal_cents on the final payment.

    Returns (principal_part, interest_part).
    """
    if apr_bps == 0:
        interest_part = 0
    else:
        r = (Decimal(apr_bps) / Decimal(10000)) / Decimal(12)
        interest_d = Decimal(remaining_principal_cents) * r
        interest_part = int(interest_d.to_integral_value(rounding=ROUND_FLOOR))
    principal_part = amount_due_cents - interest_part
    if principal_part > remaining_principal_cents:
        principal_part = remaining_principal_cents
    if principal_part < 0:
        principal_part = 0
    return principal_part, interest_part


# ── Default rate ───────────────────────────────────────────────────────────


def compute_default_rate(default_count: int, lifetime_payment_count: int) -> float:
    """default_count / max(1, lifetime_payment_count), 6 dp half-up."""
    denom = max(1, lifetime_payment_count)
    value = Decimal(default_count) / Decimal(denom)
    return round_half_up_6dp(value)


# ── Mileage overage penalty ────────────────────────────────────────────────


def mileage_penalty_cents(odometer_reading: int, mileage_allowance: int) -> int:
    overage = max(0, odometer_reading - mileage_allowance)
    return overage * PENALTY_PER_MILE_CENTS


def mileage_overage(odometer_reading: int, mileage_allowance: int) -> int:
    return max(0, odometer_reading - mileage_allowance)


# ── Lease-end total ────────────────────────────────────────────────────────


def lease_end_total_cents(mileage_penalty: int, disposition_fee: int, purchase_option: int) -> int:
    return mileage_penalty + disposition_fee + purchase_option


# ── Gap premium ────────────────────────────────────────────────────────────


def gap_monthly_premium_cents(financed_amount_cents: int) -> int:
    """ceil(financed_amount_cents * GAP_PREMIUM_BPS / 10000)."""
    d = Decimal(financed_amount_cents) * Decimal(GAP_PREMIUM_BPS) / Decimal(10000)
    return int(d.to_integral_value(rounding=ROUND_CEILING))


# ── Loan payoff balance ────────────────────────────────────────────────────


def loan_payoff_book_cents(remaining_principal_cents: int) -> dict:
    return {
        "variant": "BOOK",
        "payoff_cents": remaining_principal_cents,
        "components": {
            "remaining_principal_cents": remaining_principal_cents,
            "accrued_interest_cents": 0,
            "prepayment_penalty_cents": 0,
        },
    }


def loan_payoff_cash_cents(
    remaining_principal_cents: int,
    apr_bps: int,
    clock_day_index: int,
    last_paid_or_origination_day_index: int,
) -> dict:
    elapsed_days = max(0, clock_day_index - last_paid_or_origination_day_index)
    if apr_bps == 0 or remaining_principal_cents == 0:
        accrued = 0
    else:
        r = (Decimal(apr_bps) / Decimal(10000)) / Decimal(12)
        accrued_d = Decimal(remaining_principal_cents) * r * Decimal(elapsed_days) / Decimal(30)
        accrued = int(accrued_d.to_integral_value(rounding=ROUND_FLOOR))
    penalty_d = Decimal(remaining_principal_cents) * Decimal(PREPAYMENT_PENALTY_BPS) / Decimal(10000)
    penalty = int(penalty_d.to_integral_value(rounding=ROUND_CEILING))
    payoff = remaining_principal_cents + accrued + penalty
    return {
        "variant": "CASH",
        "payoff_cents": payoff,
        "components": {
            "remaining_principal_cents": remaining_principal_cents,
            "accrued_interest_cents": accrued,
            "prepayment_penalty_cents": penalty,
        },
    }


# ── Purchase quote ─────────────────────────────────────────────────────────


def purchase_quote_at_maturity(residual_value_cents: int) -> dict:
    purchase = residual_value_cents + PURCHASE_OPTION_FEE_CENTS
    return {
        "variant": "AT_MATURITY",
        "purchase_option_cents": purchase,
        "components": {
            "residual_value_cents": residual_value_cents,
            "purchase_option_fee_cents": PURCHASE_OPTION_FEE_CENTS,
            "remaining_lease_value_cents": 0,
        },
    }


def purchase_quote_early_buyout(
    residual_value_cents: int,
    payments_scheduled_count: int,
    payments_made_count: int,
    monthly_payment_cents: int,
) -> dict:
    unpaid = max(0, payments_scheduled_count - payments_made_count)
    remaining_lease_value = unpaid * monthly_payment_cents
    purchase = residual_value_cents + PURCHASE_OPTION_FEE_CENTS + remaining_lease_value
    return {
        "variant": "EARLY_BUYOUT",
        "purchase_option_cents": purchase,
        "components": {
            "residual_value_cents": residual_value_cents,
            "purchase_option_fee_cents": PURCHASE_OPTION_FEE_CENTS,
            "remaining_lease_value_cents": remaining_lease_value,
        },
    }


# ── Disposition fee ────────────────────────────────────────────────────────


def disposition_fee_for_election(election: str) -> int:
    """RETURN → DISPOSITION_FEE_CENTS, otherwise 0."""
    return DISPOSITION_FEE_CENTS if election == "RETURN" else 0
