"""Rounding helpers.

PRD §2.7: rounding is half up everywhere and the number of decimal places is
fixed per quantity class — energy (MWh) at 3, money at 2, equivalent full
cycles at 4, per-sample error ratios at 4, scores/percentages at 2, obligation
hours/percentages at 2, elapsed years at 4, apparent power at 3.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

_Q = {
    0: Decimal("1"),
    1: Decimal("0.1"),
    2: Decimal("0.01"),
    3: Decimal("0.001"),
    4: Decimal("0.0001"),
}


def D(value):
    """Coerce to Decimal via str() so float artefacts never leak into money."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rnd(value, places):
    """round_half_up to `places` decimals, returned as a Decimal."""
    try:
        return D(value).quantize(_Q[places], rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return D(value)


def f(value, places):
    """round_half_up to `places` decimals, returned as a JSON-friendly float."""
    return float(rnd(value, places))


def r2(value):
    return f(value, 2)


def r3(value):
    return f(value, 3)


def r4(value):
    return f(value, 4)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def finite(value):
    try:
        d = D(value)
    except Exception:
        return False
    return d.is_finite()
