"""Decimal arithmetic helpers (PRD §2.7).

All monetary and rate figures carry 2 decimal places and are rounded half up
unless stated otherwise. Never float arithmetic for money.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

ZERO = Decimal("0")


def dec(value):
    """Coerce an int / float / str / Decimal into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places):
    """Round half up to `places` decimal places, returning a Decimal."""
    q = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def money(value):
    return round_half_up(value, 2)


def pct(value):
    return round_half_up(value, 2)
