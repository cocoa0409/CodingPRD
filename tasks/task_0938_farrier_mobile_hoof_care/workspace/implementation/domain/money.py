"""Integer-cent arithmetic (PRD 2.5).

All money is integer cents.  Percentages are basis points against a
denominator of 10000.  Half-up -- floor(x + 1/2) -- is the only rounding mode
in the specification; nothing ever truncates or rounds half-even.
"""

from core.constants import BASIS_POINT_DENOMINATOR, SHOES_PER_PAIR


def round_half_up_div(numerator, denominator):
    """floor(numerator / denominator + 1/2) computed exactly on integers."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return (2 * numerator + denominator) // (2 * denominator)


def apply_bp(base, bp):
    """base * bp / 10000, rounded half up."""
    return round_half_up_div(base * bp, BASIS_POINT_DENOMINATOR)


def ceil_div(numerator, denominator):
    return -(-numerator // denominator)


def pairs_for_shoe_count(shoe_count):
    """Shoes leave stock in left/right pairs; an odd shoe draws a whole pair."""
    return ceil_div(shoe_count, SHOES_PER_PAIR)
