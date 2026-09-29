"""Money and rate arithmetic (PRD 2.6).

Integer cents everywhere. Rounding is always round-half-up: round the exact
rational value to the nearest integer, ties away from zero. Apportionment is
always largest-remainder against the EXACT rational share, never against the
displayed four-decimal percentage.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 50

ZERO = Decimal(0)
ONE = Decimal(1)


def dec(value):
    """Exact Decimal from an int / float / str / Decimal."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value):
    """Round an exact Decimal to an integer, ties away from zero."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value):
    """Round an exact Decimal to exactly four decimal places, ties away."""
    return dec(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def pct_out(value):
    """Serialise a 4dp Decimal percentage as a JSON number."""
    return float(dec(value))


def largest_remainder(total, weights):
    """Apportion `total` integer cents across weighted keys.

    `weights` is an ordered sequence of (key, Decimal weight). The weights are
    used as exact rational shares (they are expected to sum to 1; callers
    normalise beforehand). Each key first receives the floor of its exact
    share; the leftover cents are then handed out one at a time in descending
    order of truncated fractional part, ties broken by key ascending.

    Returns {key: cents}; the parts sum exactly to `total`.
    """
    result = {}
    fracs = []
    assigned = 0
    for key, weight in weights:
        raw = dec(total) * dec(weight)
        base = int(raw.to_integral_value(rounding="ROUND_FLOOR"))
        result[key] = base
        assigned += base
        fracs.append((key, raw - Decimal(base)))
    leftover = int(total) - assigned
    if leftover > 0:
        order = sorted(fracs, key=lambda item: (-item[1], item[0]))
        for index in range(leftover):
            key = order[index % len(order)][0]
            result[key] += 1
    elif leftover < 0:
        # Defensive: only reachable with pathological weights summing > 1.
        order = sorted(fracs, key=lambda item: (item[1], item[0]))
        for index in range(-leftover):
            key = order[index % len(order)][0]
            result[key] -= 1
    return result


def normalised_weights(rows, pct_key="allocation_pct", key_field="state_code"):
    """Pinned four-decimal percentages, normalised by their own sum.

    Four-decimal percentages need not sum to exactly one (three equal thirds
    pin as 0.3333 each), so every recomputation divides each row's pinned
    percentage by the sum of the pinned set before apportioning.
    """
    ordered = sorted(rows, key=lambda r: r.get(key_field) or "")
    total = sum((dec(r.get(pct_key)) for r in ordered), ZERO)
    if total == 0:
        if not ordered:
            return []
        even = ONE / Decimal(len(ordered))
        return [(r.get(key_field), even) for r in ordered]
    return [(r.get(key_field), dec(r.get(pct_key)) / total) for r in ordered]
