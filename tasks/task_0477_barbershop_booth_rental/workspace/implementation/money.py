"""Monetary rounding: half-up to whole cents using Decimal (PRD §2.6)."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up_cents(value):
    """Round a Decimal/number to the nearest whole cent, half-up. Returns int cents."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of(base_cents, pct):
    """base_cents * pct / 100, rounded half-up to whole cents. base/pct are exact."""
    base = Decimal(str(base_cents))
    p = Decimal(str(pct))
    return round_half_up_cents(base * p / Decimal("100"))
