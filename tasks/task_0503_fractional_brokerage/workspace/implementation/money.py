"""Monetary precision helpers (PRD §2.5). All money is whole cents; non-integer
cent results round half up. Basis-point rates divide by 10000 then round half up.
Share quantities are tracked to 6 dp and truncated toward zero where specified."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN


def D(x):
    return Decimal(str(x))


def round_half_up(value):
    """Round a Decimal/number to the nearest whole integer, half up."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps_of_cents(cents, bps):
    """Apply a basis-point rate to a cent amount: cents * bps / 10000, half up."""
    return round_half_up(D(cents) * D(bps) / D(10000))


def truncate_shares(value):
    """Truncate a share quantity toward zero at 6 decimal places (PRD §2.5)."""
    q = D(value).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    return float(q)


def shares_str(value):
    """Normalize a share quantity to a float at 6dp (avoids fp drift in output)."""
    return float(D(value).quantize(Decimal("0.000001"), rounding=ROUND_DOWN))
