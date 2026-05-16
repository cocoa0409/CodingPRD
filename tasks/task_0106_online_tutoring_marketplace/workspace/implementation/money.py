"""Monetary calculations — integer cents with explicit round-half-up rules."""

from decimal import Decimal, ROUND_HALF_UP


def to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up_to_int(value):
    """Round a Decimal value to the nearest integer using ROUND_HALF_UP."""
    d = to_decimal(value)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def commission_rate(lifetime_completed):
    """Return commission rate based on tutor's lifetime completed sessions."""
    if lifetime_completed >= 100:
        return Decimal("0.10")
    if lifetime_completed >= 20:
        return Decimal("0.15")
    return Decimal("0.20")
