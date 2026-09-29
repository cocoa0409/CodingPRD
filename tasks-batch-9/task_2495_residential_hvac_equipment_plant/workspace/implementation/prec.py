"""Decimal / Fraction precision helpers (PRD 2.6 -- ROUND_HALF_UP everywhere)."""

from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction


def dec(value):
    """Coerce an int / float / str / Decimal / Fraction into a Decimal exactly."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, Fraction):
        return Decimal(value.numerator) / Decimal(value.denominator)
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def q(value, places):
    """Round half up to `places` decimal places, returning a Decimal."""
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def q0_int(value):
    """Round half up to a whole number, returning an int."""
    return int(q(value, 0))


def q_frac(fraction, places):
    """Round a Fraction half up to `places` places without binary error."""
    scale = 10 ** places
    scaled = Fraction(fraction) * scale
    whole = scaled.numerator // scaled.denominator
    remainder = scaled - whole
    if remainder >= Fraction(1, 2):
        whole += 1
    return q(Decimal(whole) / Decimal(scale), places)


def floor_div(numerator, denominator):
    """Integer floor of numerator / denominator (both non-negative integers)."""
    if denominator == 0:
        return 0
    return numerator // denominator


def json_number(value):
    """Render a Decimal for JSON output."""
    if isinstance(value, Decimal):
        return float(value)
    return value
