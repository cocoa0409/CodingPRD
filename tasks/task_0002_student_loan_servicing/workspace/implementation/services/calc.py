"""Pure calculation routines per SCAFFOLD §1.3."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, getcontext

# Use plenty of precision for intermediate decimal math.
getcontext().prec = 60

# Constants from SCAFFOLD §1.3
STANDARD_TERM_MONTHS = 120
IBR_DISCRETIONARY_THRESHOLD_PCT = 150
PAYE_DISCRETIONARY_THRESHOLD_PCT = 150
SAVE_DISCRETIONARY_THRESHOLD_PCT = 225
IBR_PAYMENT_PCT = Decimal("0.15")
PAYE_PAYMENT_PCT = Decimal("0.10")
SAVE_PAYMENT_PCT = Decimal("0.05")
TREASURY_OFFSET_FEE_PCT = Decimal("0.1825")
DAILY_ACCRUAL_BASIS_DAYS = 365

POVERTY_LINES_BY_STATE = {
    "CONTIGUOUS": {
        1: 1506000,
        2: 2034000,
        3: 2562000,
        4: 3090000,
        5: 3618000,
    },
    "AK": {
        1: 1883000,
        2: 2542000,
        3: 3201000,
        4: 3860000,
        5: 4519000,
    },
    "HI": {
        1: 1732000,
        2: 2339000,
        3: 2946000,
        4: 3553000,
        5: 4160000,
    },
}


def round_half_up(value: Decimal) -> int:
    """Round a Decimal value to the nearest whole integer using ROUND_HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def poverty_line(state: str, family_size: int) -> int:
    """Look up annual poverty line in cents.

    Family sizes beyond the table extend by linear extrapolation using the largest tabulated
    increment (size-5 - size-4); the table covers 1..5 explicitly.
    """
    table = POVERTY_LINES_BY_STATE[state]
    if family_size in table:
        return table[family_size]
    # Extrapolate beyond size 5
    if family_size > 5:
        increment = table[5] - table[4]
        return table[5] + (family_size - 5) * increment
    # Should never happen — family_size >= 1 enforced upstream
    raise ValueError(f"family_size out of range: {family_size}")


# ---------- plan_monthly_payment ----------


def standard_10yr_monthly_payment(
    outstanding_principal_cents: int, interest_rate_bps: int
) -> int:
    """STANDARD_10YR amortization. Returns whole cents, round_half_up."""
    P = Decimal(outstanding_principal_cents)
    # r_monthly = bps/10000/12
    r_monthly = Decimal(interest_rate_bps) / Decimal(10000) / Decimal(12)
    n = STANDARD_TERM_MONTHS
    if r_monthly == 0:
        return round_half_up(P / Decimal(n))
    one_plus_r = Decimal(1) + r_monthly
    pow_n = one_plus_r ** n
    monthly = P * r_monthly * pow_n / (pow_n - Decimal(1))
    return round_half_up(monthly)


def plan_monthly_payment(
    plan_type: str,
    outstanding_principal_cents: int,
    interest_rate_bps: int,
    agi_cents,
    family_size,
    state_of_residence: str,
) -> int:
    """Returns whole cents monthly payment per SCAFFOLD §1.3 plan_monthly_payment."""
    if plan_type == "STANDARD_10YR":
        return standard_10yr_monthly_payment(outstanding_principal_cents, interest_rate_bps)

    # IDR plans: need poverty line lookup
    pov = Decimal(poverty_line(state_of_residence, int(family_size)))
    agi = Decimal(int(agi_cents))

    if plan_type == "IBR":
        threshold = Decimal(IBR_DISCRETIONARY_THRESHOLD_PCT) * pov / Decimal(100)
        discretionary_annual = max(Decimal(0), agi - threshold)
        idr_monthly_decimal = discretionary_annual * IBR_PAYMENT_PCT / Decimal(12)
        idr_monthly = round_half_up(idr_monthly_decimal)
        standard = standard_10yr_monthly_payment(outstanding_principal_cents, interest_rate_bps)
        return min(idr_monthly, standard)
    if plan_type == "PAYE":
        threshold = Decimal(PAYE_DISCRETIONARY_THRESHOLD_PCT) * pov / Decimal(100)
        discretionary_annual = max(Decimal(0), agi - threshold)
        idr_monthly_decimal = discretionary_annual * PAYE_PAYMENT_PCT / Decimal(12)
        idr_monthly = round_half_up(idr_monthly_decimal)
        standard = standard_10yr_monthly_payment(outstanding_principal_cents, interest_rate_bps)
        return min(idr_monthly, standard)
    if plan_type == "SAVE":
        threshold = Decimal(SAVE_DISCRETIONARY_THRESHOLD_PCT) * pov / Decimal(100)
        discretionary_annual = max(Decimal(0), agi - threshold)
        save_monthly_decimal = discretionary_annual * SAVE_PAYMENT_PCT / Decimal(12)
        return round_half_up(save_monthly_decimal)
    raise ValueError(f"Unknown plan_type: {plan_type}")


# ---------- payment_allocation ----------


def payment_allocation(
    amount_cents: int,
    loan_status: str,
    payment_source: str,
    accrued_interest_cents: int,
    outstanding_principal_cents: int,
):
    """Returns (applied_to_fees, applied_to_interest, applied_to_principal, remaining).

    A non-zero remaining means the payment exceeds the loan balance and the caller
    must raise ERR_PAYMENT_EXCEEDS_BALANCE.
    """
    remaining = amount_cents

    # Bucket 1: collection fees — only on DEFAULT + TREASURY_OFFSET
    if loan_status == "DEFAULT" and payment_source == "TREASURY_OFFSET":
        # floor(amount * 0.1825) per-payment
        fees_due = int((Decimal(amount_cents) * TREASURY_OFFSET_FEE_PCT).to_integral_value(rounding="ROUND_FLOOR"))
        applied_to_fees = min(remaining, fees_due)
    else:
        applied_to_fees = 0
    remaining -= applied_to_fees

    # Bucket 2: accrued interest
    applied_to_interest = min(remaining, accrued_interest_cents)
    remaining -= applied_to_interest

    # Bucket 3: outstanding principal
    applied_to_principal = min(remaining, outstanding_principal_cents)
    remaining -= applied_to_principal

    return applied_to_fees, applied_to_interest, applied_to_principal, remaining


# ---------- daily interest accrual ----------


def daily_interest_increment(outstanding_principal_cents: int, interest_rate_bps: int) -> int:
    """Daily interest accrual per PRD §2.7: P * bps / 10000 / 365, round_half_up cents."""
    P = Decimal(outstanding_principal_cents)
    daily = P * Decimal(interest_rate_bps) / Decimal(10000) / Decimal(DAILY_ACCRUAL_BASIS_DAYS)
    return round_half_up(daily)
