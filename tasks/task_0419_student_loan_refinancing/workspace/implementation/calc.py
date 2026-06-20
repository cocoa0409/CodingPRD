"""Calculation rules (PRD §3 / scaffold §1.3).

All money is integer cents; APRs are integer basis points. Fractional cents are
rounded half up. dti_ratio is rounded half up to exactly four decimal places.
Decimal is used throughout for precision (never float).
"""
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    AMORT_FACTORS,
    APR_FLOOR_BPS,
    AUTOPAY_DISCOUNT_BPS,
    BAND_ORDER,
    BAND_SURCHARGE_BPS,
    DAYS_PER_YEAR,
    MEMBER_DISCOUNT_BPS,
)


def band_index(band):
    return BAND_ORDER.index(band)


def round_half_up_int(value):
    """Round a Decimal to the nearest whole integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def soft_pull(fico_band):
    """Map self-reported band one notch toward the center (PRD §3.2).

    Positions 0/1 move up one; positions 2/3 move down one.
    """
    i = band_index(fico_band)
    if i <= 1:
        return BAND_ORDER[i + 1]
    return BAND_ORDER[i - 1]


def estimated_monthly_payment_cents(requested_principal_cents, term_months):
    """Requested principal * flat amortization factor, rounded half up (PRD §3.2)."""
    factor = Decimal(AMORT_FACTORS[term_months])
    return round_half_up_int(Decimal(requested_principal_cents) * factor)


def dti_ratio(requested_principal_cents, term_months, combined_income_cents):
    """Annual debt service / combined income, half up to 4 decimals (PRD §3.2).

    Returns a Decimal quantized to 4 places (e.g. Decimal('0.4300')).
    """
    est_monthly = estimated_monthly_payment_cents(requested_principal_cents, term_months)
    annual_debt_service = est_monthly * 12
    ratio = Decimal(annual_debt_service) / Decimal(combined_income_cents)
    return ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def estimated_apr_bps(base_apr_bps, index_apr_bps, rate_type, soft_pull_fico_band):
    """Prequal estimate APR; integer bps, no autopay/member discount (PRD §3.2)."""
    index = index_apr_bps if rate_type == "VARIABLE" else 0
    surcharge = BAND_SURCHARGE_BPS[soft_pull_fico_band]
    return base_apr_bps + index + surcharge


def locked_apr_bps(estimated_apr, autopay_elected, member_tier):
    """Final APR: autopay first, then member-tier, then floor clamp (PRD §3.4)."""
    apr = estimated_apr
    after_autopay = apr - (AUTOPAY_DISCOUNT_BPS if autopay_elected else 0)
    after_member = after_autopay - MEMBER_DISCOUNT_BPS[member_tier]
    return max(after_member, APR_FLOOR_BPS)


def floor_days_between(start_dt, end_dt):
    """Count of whole days between two instants, floored (PRD §3.9).

    Daily accrual counts whole days; negative spans floor to 0 (never negative).
    """
    delta = end_dt - start_dt
    days = delta.days
    if delta.days < 0 and (delta.seconds or delta.microseconds):
        # timedelta.days is already floor for negatives; keep as-is but clamp.
        pass
    return max(days, 0)


def accrue_interest_cents(principal_balance_cents, locked_apr_bps_value, days):
    """Daily-simple accrual; round half up once after multiplying by days (PRD §3.9).

    daily_rate = locked_apr_bps / 10000 / 365
    new_interest = round_half_up(principal_balance * daily_rate * days)
    """
    if days <= 0:
        return 0
    daily_rate = Decimal(locked_apr_bps_value) / Decimal(10000) / Decimal(DAYS_PER_YEAR)
    product = Decimal(principal_balance_cents) * daily_rate * Decimal(days)
    return round_half_up_int(product)


def waterfall(amount_cents, accrued_interest_cents, principal_balance_cents):
    """Interest-first allocation (PRD §3.9). Returns (interest_portion, principal_portion).

    interest_portion = min(amount, accrued_interest)
    remainder = amount - interest_portion
    principal_portion = min(remainder, principal_balance)
    Overpayment beyond interest + full principal is dropped.
    """
    interest_portion = min(amount_cents, accrued_interest_cents)
    remainder = amount_cents - interest_portion
    principal_portion = min(remainder, principal_balance_cents)
    return interest_portion, principal_portion
