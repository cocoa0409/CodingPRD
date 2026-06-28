"""Monetary calculations with strict round-half-up to whole cents (PRD §2.5)."""
from decimal import Decimal, ROUND_HALF_UP


def _to_decimal(value):
    # Convert float/int/str to Decimal via str() to avoid binary-float artifacts.
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    """Round a numeric value to the nearest whole integer, half away from zero
    (upward for positives). Returns a Python int (cents)."""
    d = _to_decimal(value)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_valuation_cents(weight_lb, price_cents_per_lb):
    """round_half_up(weight_lb * price_cents_per_lb)."""
    return round_half_up(_to_decimal(weight_lb) * _to_decimal(price_cents_per_lb))
