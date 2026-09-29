"""Decimal precision helpers (PRD 2.8).  Never float arithmetic, never round()."""
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal(0)
ONE = Decimal(1)


def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return None
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places, returning a Decimal."""
    quantum = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu4(value):
    return rhu(value, 4)


def rhu2(value):
    return rhu(value, 2)


def cents(value):
    """Whole-cent integer, rounded half up."""
    return int(rhu(value, 0))


def out(value):
    """Serialise a Decimal for JSON output."""
    if value is None:
        return None
    return float(value)
