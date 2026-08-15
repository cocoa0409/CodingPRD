"""Numeric helpers: Decimal-based half-up rounding (PRD section 2.7) and
month arithmetic for certification validity."""

import calendar
from decimal import Decimal, ROUND_HALF_UP


def D(x):
    """Coerce to Decimal without binary-float noise."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rhu(x, places):
    """Round half-up to the given number of decimal places; returns Decimal."""
    return D(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def rhu_int(x):
    """Round half-up to an integer; returns int."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num2(x):
    """Round half-up to 2dp and return as a JSON float."""
    return float(rhu(x, 2))


def num4(x):
    """Round half-up to 4dp and return as a JSON float."""
    return float(rhu(x, 4))


def add_months(dt, months):
    """Add calendar months, clamping the day to the target month's length."""
    total = dt.year * 12 + (dt.month - 1) + months
    y, m = divmod(total, 12)
    m += 1
    last = calendar.monthrange(y, m)[1]
    return dt.replace(year=y, month=m, day=min(dt.day, last))
