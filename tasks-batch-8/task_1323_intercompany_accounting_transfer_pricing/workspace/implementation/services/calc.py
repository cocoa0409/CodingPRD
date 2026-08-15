"""Calculation rules (SCAFFOLD Table 3 / PRD 2.6 + section 3).

All monetary values are integer cents; margins/markups are integer basis points.
Every stated rounding is round-half-up via Decimal — never float, never banker's.
"""
from decimal import Decimal, ROUND_HALF_UP

CBCR_THRESHOLD_EUR = 750000000
POOL_SPREAD_BP = 85
_POOL_SPREAD = Decimal(POOL_SPREAD_BP) / Decimal(10000) / Decimal(365)


def rhu(value):
    """Round a Decimal half-up to a whole integer."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cbc_required(group_revenue_eur):
    """cbcr_threshold_check: inclusive integer comparison, no rounding."""
    return group_revenue_eur >= CBCR_THRESHOLD_EUR


def provisional_price_cents(cost_base_cents, markup_bp):
    """provisional_price_calc: round_half_up(cost * (10000 + markup) / 10000).
    Zero cost base (system true-up adjustment) -> 0."""
    if cost_base_cents == 0:
        return 0
    return rhu(Decimal(cost_base_cents) * Decimal(10000 + markup_bp) / Decimal(10000))


def margin_bp_of(revenue_cents, cost_base_cents):
    """round_half_up((revenue - cost) * 10000 / cost). Zero cost base -> 0."""
    if cost_base_cents == 0:
        return 0
    return rhu(Decimal(revenue_cents - cost_base_cents) * Decimal(10000)
               / Decimal(cost_base_cents))


def nearest_rank(sorted_vals, p):
    """interquartile_range: rank(p) = ceil(p * n / 100), 1-indexed."""
    n = len(sorted_vals)
    rank = -(-p * n // 100)
    if rank < 1:
        rank = 1
    return sorted_vals[rank - 1]


def interquartile_range(comparables_bp):
    s = sorted(comparables_bp)
    return nearest_rank(s, 25), nearest_rank(s, 50), nearest_rank(s, 75)


def true_up_calculation(agreement, txs):
    """true_up_calculation over MATCHED + ELIMINATED transactions.

    Returns (actual_margin_bp, true_up_amount_cents). Range membership is
    inclusive; TO_MEDIAN targets the pinned median, TO_RANGE_EDGE the nearest
    edge with ties resolving to the lower edge.
    """
    s_cost = sum(t["cost_base_cents"] for t in txs)
    s_booked = sum(t["provider_revenue_cents"] for t in txs)
    actual = margin_bp_of(s_booked, s_cost)
    lo = agreement.get("pinned_p25_bp")
    med = agreement.get("pinned_median_bp")
    hi = agreement.get("pinned_p75_bp")
    if lo is None or med is None or hi is None:
        return actual, 0
    if lo <= actual <= hi:
        return actual, 0
    if agreement.get("true_up_method") == "TO_MEDIAN":
        target = med
    else:  # TO_RANGE_EDGE
        target = lo if abs(lo - actual) <= abs(hi - actual) else hi
    target_price = rhu(Decimal(s_cost) * Decimal(10000 + target) / Decimal(10000))
    return actual, target_price - s_booked


def interest_cents(base_balance_day_cents):
    """pool_interest_allocation: base * 85/10000/365, round-half-up, signed."""
    return rhu(Decimal(base_balance_day_cents) * _POOL_SPREAD)


def fee_share_cents(admin_fee_cents, abs_balance, fee_base):
    """pool_fee_allocation: round-per-position first."""
    return rhu(Decimal(admin_fee_cents) * Decimal(abs_balance) / Decimal(fee_base))
