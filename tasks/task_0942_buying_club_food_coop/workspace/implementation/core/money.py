"""Money and allocation primitives.

All money is integer cents.  `round_half_up` is half-away-from-zero at the whole
cent.  `largest_remainder` is the single shared pro-rata scheme: floor shares
first, then the leftover cents handed out one each in descending order of the
discarded fraction, ties broken by the caller's ordering (which is always
ascending created_at).
"""

from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal/Fraction/number half away from zero to a whole integer."""
    if isinstance(value, Fraction):
        value = Decimal(value.numerator) / Decimal(value.denominator)
    else:
        value = D(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    """Exact integer ceiling of numerator / denominator (denominator > 0)."""
    return -((-numerator) // denominator)


def floor_pct(total, pct):
    """floor(total * pct) exactly, with pct given as a decimal string."""
    frac = Fraction(D(pct))
    return (Fraction(total) * frac).__floor__()


def largest_remainder(total, weights):
    """Split `total` across recipients whose weights are `weights`.

    The recipients must already be in ascending created_at order.  Returns
    (shares, ranked_indices) where ranked_indices is the descending-remainder
    ordering (ties broken by the caller's ordering) used to hand out leftovers.
    """
    n = len(weights)
    if n == 0:
        return [], []
    denom = sum(weights)
    if denom <= 0 or total == 0:
        return [0] * n, list(range(n))
    exact = [Fraction(total * w, denom) for w in weights]
    base = [e.__floor__() for e in exact]
    remainders = [exact[i] - base[i] for i in range(n)]
    ranked = sorted(range(n), key=lambda i: (-remainders[i], i))
    leftover = total - sum(base)
    shares = list(base)
    for k in range(leftover):
        shares[ranked[k]] += 1
    return shares, ranked
