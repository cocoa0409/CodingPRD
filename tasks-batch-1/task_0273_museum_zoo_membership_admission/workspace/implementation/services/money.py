"""Money rounding (PRD §2.6).

All amounts are integer cents. When a price is multiplied by a fractional factor,
the result is rounded to the nearest whole cent using round-half-up, applied at
EACH per-component multiplication, never deferred to the final sum.
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a numeric value to the nearest integer using round-half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def discounted_cents(base_cents, discount_pct):
    """base_cents * (1 - discount_pct), rounded half-up to whole cents."""
    factor = Decimal("1") - Decimal(str(discount_pct))
    raw = Decimal(base_cents) * factor
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
