"""Whole-cent money discipline (PRD 2.6).  Never float, always Decimal with
ROUND_HALF_UP — a value exactly halfway between two cents rounds away from zero.
"""

from decimal import Decimal, ROUND_HALF_UP


def dec(value):
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal to a whole unit, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
