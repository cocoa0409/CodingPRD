"""Precision helpers: all money integer cents; round_half_up at pinned steps."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up_cents(value):
    """Round a Decimal-compatible numeric to whole cents, half-up."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mul_pct_round(amount_cents, pct):
    """round_half_up(amount_cents * pct / 100). pct may be fractional."""
    return round_half_up_cents(Decimal(amount_cents) * Decimal(str(pct)) / Decimal(100))


def fx_convert(amount_cents, rate):
    """round_half_up(amount_cents * rate)."""
    return round_half_up_cents(Decimal(amount_cents) * Decimal(str(rate)))
