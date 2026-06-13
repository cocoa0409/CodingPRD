"""Monetary / ratio rounding — round-half-up only (PRD §2.5).

A value whose fractional part is exactly one-half rounds up to the next whole
cent. We use Decimal with ROUND_HALF_UP to avoid float drift. No other rounding
mode is ever used in this system.
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a numeric value (int/float/Decimal) to the nearest whole integer
    using round-half-up. Inputs are first converted to an exact Decimal."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mul_round(amount_cents, factor):
    """round_half_up(amount_cents * factor) computed exactly in Decimal."""
    return round_half_up(Decimal(str(amount_cents)) * Decimal(str(factor)))


def ratio_round_4dp(numerator, denominator):
    """round_half_up to exactly four decimal places of numerator/denominator.
    Returns a float for JSON emission. denominator must be > 0."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)
