"""Monetary precision helpers (PRD section 2.6)."""
from decimal import Decimal, ROUND_HALF_UP


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    """Round a Decimal amount of cents to a whole integer, half-up."""
    return int(round_half_up(value, 0))


def pct(amount_cents, rate):
    """round_half_up(amount * rate) as whole cents."""
    return cents(dec(amount_cents) * dec(rate))
