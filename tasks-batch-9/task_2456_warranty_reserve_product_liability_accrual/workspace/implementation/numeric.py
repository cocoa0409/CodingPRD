"""Exact integer arithmetic helpers (PRD §2.6).

Every monetary figure is an exact integer count of cents; every rate is an
integer count of basis points or parts per million.  ``round_half_up`` rounds an
exact rational to the nearest integer with ties going away from zero.  No
floating-point value is ever produced or persisted.
"""


def round_half_up(numerator, denominator):
    """Round the exact rational ``numerator / denominator`` to the nearest int.

    Ties go away from zero.  Both arguments must be integers.
    """
    if denominator == 0:
        raise ZeroDivisionError("round_half_up denominator is zero")
    n, d = int(numerator), int(denominator)
    if d < 0:
        n, d = -n, -d
    if n >= 0:
        return (2 * n + d) // (2 * d)
    return -((-2 * n + d) // (2 * d))


def rhu(numerator, denominator=1):
    return round_half_up(numerator, denominator)
