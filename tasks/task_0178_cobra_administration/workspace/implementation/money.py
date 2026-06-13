"""Monetary rounding — whole cents, round-half-up (PRD §2.6).

A value whose fractional part is exactly one-half rounds up to the next whole
cent. We use Decimal with ROUND_HALF_UP to avoid float drift.
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a numeric value (int/float/Decimal/Fraction-like) to the nearest
    whole integer using round-half-up. Inputs are first converted to an exact
    Decimal."""
    if isinstance(value, Decimal):
        d = value
    else:
        # str() of a float preserves the shortest round-trippable repr; but to
        # be exact for ratios we prefer callers pass Decimal. For ints this is
        # exact.
        d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mul_round(amount_cents, factor):
    """round_half_up(amount_cents * factor) computed exactly in Decimal."""
    return round_half_up(Decimal(amount_cents) * Decimal(str(factor)))


def ratio_round(amount_cents, numerator, denominator):
    """round_half_up(amount_cents * numerator / denominator) computed exactly."""
    return round_half_up(
        (Decimal(amount_cents) * Decimal(numerator)) / Decimal(denominator)
    )
