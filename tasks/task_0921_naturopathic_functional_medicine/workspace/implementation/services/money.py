"""Rounding primitives. Money is always whole cents, never a float (PRD 2.8)."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    """Round to a whole unit, half away from zero (PRD 2.8)."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_units(value):
    """Round up to a whole unit."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_CEILING))
