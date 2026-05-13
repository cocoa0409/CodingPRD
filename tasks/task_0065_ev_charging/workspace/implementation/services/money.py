"""Monetary arithmetic helpers using Decimal + ROUND_HALF_UP."""

from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value) -> int:
    """Round a numeric/Decimal value to the nearest integer, half-up."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cents_from_milli(milli_kwh: int, rate_cents_per_kwh: int) -> int:
    """milli_kwh * rate / 1000, rounded half up to integer cents."""
    return round_half_up(Decimal(milli_kwh) * Decimal(rate_cents_per_kwh) / Decimal(1000))


def bps_apply(amount: int, bps: int, divisor: int = 10_000) -> int:
    """amount * bps / divisor, rounded half up."""
    return round_half_up(Decimal(amount) * Decimal(bps) / Decimal(divisor))
