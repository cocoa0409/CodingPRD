"""Integer-cent / basis-point arithmetic.  No floats anywhere."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) -> int.  Halves go away from zero."""
    if denominator == 0:
        raise ZeroDivisionError("round_half_up denominator is zero")
    q = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(q.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_div(numerator, denominator):
    """Truncate toward negative infinity."""
    if denominator == 0:
        raise ZeroDivisionError("floor_div denominator is zero")
    return int(numerator) // int(denominator)


def bp_share_half_up(pool_cents, bp):
    """pool * bp / 10000, rounded half up."""
    return round_half_up(int(pool_cents) * int(bp), 10000)


def cyclic_allocate(pool_cents, participants):
    """The assessment allocator of PRD 3.2.

    `participants` is an already-ordered list of (key, interest_bp) pairs.
    Each line share is round_half_up(pool * interest_bp / 10000).  The drift
    (pool - sum of lines) is then distributed ONE CENT AT A TIME by cycling
    through the participants in the pinned order, wrapping as often as needed:
    a positive drift adds a cent per step, a negative drift removes one.

    Returns (shares, base_shares, drift) where `shares` is the final per-line
    list, `base_shares` the pre-drift per-line rounded values, and `drift` the
    signed drift measured before distribution.
    """
    base = [bp_share_half_up(pool_cents, bp) for _, bp in participants]
    shares = list(base)
    drift = int(pool_cents) - sum(base)
    n = len(participants)
    if n and drift:
        step = 1 if drift > 0 else -1
        remaining = abs(drift)
        i = 0
        while remaining > 0:
            shares[i % n] += step
            i += 1
            remaining -= 1
    return shares, base, drift


def floor_then_topup(residue_cents, participants):
    """The deductible waterfall allocator of PRD 3.7.

    `participants` is an already-ordered list of (key, weight) pairs.  Each
    provisional allocation is FLOORED, and the drift (>= 0, < len) is topped up
    by giving exactly one extra cent to each of the first `drift` participants
    in the pinned order -- a single pass, at most one cent each.

    Returns (allocations, drift).
    """
    total_weight = sum(w for _, w in participants)
    if total_weight <= 0:
        return [0 for _ in participants], 0
    allocs = [floor_div(int(residue_cents) * int(w), total_weight) for _, w in participants]
    drift = int(residue_cents) - sum(allocs)
    for i in range(min(drift, len(allocs))):
        allocs[i] += 1
    return allocs, drift
