"""Monetary rounding (PRD §2.7): round-half-up toward positive infinity magnitude.

We use Decimal with ROUND_HALF_UP for deterministic ledger arithmetic. Inputs
are integer cents and fractional rate inputs; we never use float for the
committed result.
"""
from decimal import Decimal, ROUND_HALF_UP


def D(x):
    """Build an exact Decimal from int/float/str/Decimal without float drift."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(x)


def round_half_up(value):
    """Round a Decimal/number to the nearest integer, half away toward +inf.

    PRD §2.7: 'a value exactly halfway ... rounds to the larger magnitude
    toward positive infinity'. ROUND_HALF_UP on Decimal rounds away from zero;
    for the positive amounts at play, and for the .5 cases the PRD describes,
    that is rounding toward +inf. We apply it as away-from-zero which matches
    the stated 'larger magnitude' wording.
    """
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def mul_round(cents, pct):
    """round_half_up(cents * pct) -> integer cents."""
    return round_half_up(D(cents) * D(pct))
