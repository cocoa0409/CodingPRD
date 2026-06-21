"""Calculation rules (SCAFFOLD §1.3 / PRD §2.5, §3).

All money is integer cents. Rounding is half-up at the single contractual step
of each rule. Decimal is used for every multiply/divide so no float drift leaks
into a cent value.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

# Wide precision so amortization powers don't lose digits.
getcontext().prec = 50

# Constants pinned by the spec.
LATE_FEE_PCT = Decimal("0.05")          # SCAFFOLD calc late_fee_assessment
MIN_CONVERSION_SCORE = 620              # PRD §3.7 / SCAFFOLD
MAX_MISSED_PAYMENTS = 3                 # PRD §3.8 / SCAFFOLD


def round_half_up(value):
    """Round a Decimal to the nearest whole cent, half up -> int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def credit_portion(amount_cents, credit_pct):
    """Per-payment credit portion = round_half_up(amount * credit_pct).

    Rounding happens here, per period, before any summing (round-then-sum).
    """
    return round_half_up(Decimal(amount_cents) * Decimal(str(credit_pct)))


def late_fee(amount_cents):
    """round_half_up(amount_cents * 0.05)."""
    return round_half_up(Decimal(amount_cents) * LATE_FEE_PCT)


def maintenance_split(cost_cents, threshold_cents):
    """Pure threshold split — no rounding. Shares reconstitute cost exactly."""
    tenant_share = min(cost_cents, threshold_cents)
    landlord_share = max(0, cost_cents - threshold_cents)
    return tenant_share, landlord_share


def max_credit_cap(locked_price_cents, max_credit_pct):
    """round_half_up(locked_price_snapshot * max_credit_pct)."""
    return round_half_up(Decimal(locked_price_cents) * Decimal(str(max_credit_pct)))


def amortized_installment(principal_cents, annual_rate_bps, term_months):
    """Standard amortization, round_half_up on the final installment."""
    P = Decimal(principal_cents)
    n = term_months
    # monthly rate as a fraction: bps/10000/12
    r = Decimal(annual_rate_bps) / Decimal(10000) / Decimal(12)
    if r == 0:
        return round_half_up(P / Decimal(n))
    one_plus_r_n = (Decimal(1) + r) ** n
    numerator = P * r * one_plus_r_n
    denominator = one_plus_r_n - Decimal(1)
    return round_half_up(numerator / denominator)
