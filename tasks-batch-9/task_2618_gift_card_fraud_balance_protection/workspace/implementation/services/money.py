"""Monetary and score arithmetic (PRD 2.6). Integer cents, Decimal maths,
half-up rounding everywhere - never float, never banker's rounding."""
from decimal import Decimal, ROUND_HALF_UP

BPS = Decimal(10000)


def round_half_up(value):
    """Round a Decimal to the nearest whole unit, halves away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bps(amount_cents, bps):
    """amount * bps / 10000, rounded half up exactly once."""
    return round_half_up(Decimal(int(amount_cents)) * Decimal(int(bps)) / BPS)


def ratio_two_dp(numerator, denominator):
    """Half-up to two decimals, clamped into [0.00, 1.00]."""
    if denominator == 0:
        return Decimal("0.00")
    value = (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if value < Decimal("0.00"):
        return Decimal("0.00")
    if value > Decimal("1.00"):
        return Decimal("1.00")
    return value


def clamp_score(raw):
    """Round half up once at the very end, then clamp into [0, 100]."""
    score = round_half_up(raw)
    if score < 0:
        return 0
    if score > 100:
        return 100
    return score
