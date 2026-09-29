"""Pure numeric helpers: half-up rounding, interval algebra, cost math."""

from decimal import Decimal, ROUND_HALF_UP, getcontext

from consts import BASE_INSTALL_CENTS, PER_MBPS_CENTS
from timeutil import minutes_between

getcontext().prec = 50


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up (away from zero) to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    """Round a Decimal amount to whole cents, half up, as an int."""
    return int(rhu(value, 0))


def ceil_div(numerator, denominator):
    value = dec(numerator) / dec(denominator)
    integral = value.to_integral_value(rounding="ROUND_FLOOR")
    if value > integral:
        integral += 1
    return int(integral)


# --------------------------------------------------------------------------
# interval algebra (half-open [start, end) instants)
# --------------------------------------------------------------------------


def merge_intervals(intervals):
    """Merge overlapping *and* touching half-open intervals; sorted output."""
    ordered = sorted((i for i in intervals if i[1] > i[0]), key=lambda i: (i[0], i[1]))
    merged = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def intersect_unions(unions):
    """Intersection of a list of merged unions."""
    unions = list(unions)
    if not unions:
        return []
    result = unions[0]
    for other in unions[1:]:
        result = _intersect_two(result, other)
        if not result:
            return []
    return result


def _intersect_two(left, right):
    out = []
    i = j = 0
    while i < len(left) and j < len(right):
        start = max(left[i][0], right[j][0])
        end = min(left[i][1], right[j][1])
        if end > start:
            out.append((start, end))
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return out


def union_minutes(union):
    total = Decimal(0)
    for start, end in union:
        total += minutes_between(start, end)
    return total


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Strict overlap of half-open intervals (adjacency does not overlap)."""
    return a_start < b_end and b_start < a_end


# --------------------------------------------------------------------------
# upgrade cost
# --------------------------------------------------------------------------


def expedite_tier_pct(subtotal_cents):
    if subtotal_cents < 500000:
        return Decimal("0.25")
    if subtotal_cents < 1500000:
        return Decimal("0.15")
    return Decimal("0.08")


def upgrade_cost(current_mbps, target_mbps, expedite):
    delta = target_mbps - current_mbps
    subtotal = BASE_INSTALL_CENTS + delta * PER_MBPS_CENTS
    fee = 0
    if expedite:
        fee = cents(dec(subtotal) * expedite_tier_pct(subtotal))
    return delta, int(subtotal), int(fee), int(subtotal) + int(fee)
