"""Calculation rules (SCAFFOLD §1.3, PRD §3.5–§3.8).

All money is integer cents. Rates are basis points (1 bps = 0.01%).
Rounding is round-half-up, applied exactly once on the summed total per the
scaffold's pinned rounding order (sum exact rationals, then round once).
"""
from decimal import Decimal, ROUND_HALF_UP

# --- Resale royalty constants (SCAFFOLD calc resale_royalty_due) -------------
ROYALTY_FLOOR_CENTS = 100000      # 1,000.00 — below this, no royalty
ROYALTY_CAP_CENTS = 1250000       # 12,500.00 — absolute per-lot cap
ROYALTY_BANDS = [
    # (upper_bound_cents or None for open top, rate_bps)
    (5000000, 400),    # 0 .. 50,000.00      -> 4.00%
    (20000000, 300),   # 50,000.00 .. 200,000.00 -> 3.00%
    (35000000, 100),   # 200,000.00 .. 350,000.00 -> 1.00%
    (50000000, 50),    # 350,000.00 .. 500,000.00 -> 0.50%
    (None, 25),        # above 500,000.00    -> 0.25%
]

# --- Minimum-next-bid constants (SCAFFOLD calc min_next_bid) -----------------
STARTING_BID_FLOOR_CENTS = 5000   # 50.00 minimum opening bid
BID_BANDS = [
    # (upper_bound_cents exclusive or None for open top, increment_cents)
    (100000, 5000),     # [0, 1,000.00)       -> +50.00
    (500000, 10000),    # [1,000.00, 5,000.00) -> +100.00
    (2000000, 25000),   # [5,000.00, 20,000.00) -> +250.00
    (None, 100000),     # [20,000.00, +inf)   -> +1,000.00
]


def round_half_up(decimal_value):
    """Round a Decimal to an integer using round-half-up. Returns int."""
    return int(decimal_value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def buyers_premium_cents(hammer_cents, tiers):
    """Tiered MARGINAL buyer's premium on the hammer.

    tiers: ordered list of {"upper_bound_cents": int|None, "rate_bps": int},
    ascending by upper_bound_cents with the open (null) tier last.

    Accumulate exact rational slices, round ONCE on the total.
    """
    H = hammer_cents
    premium_exact = Decimal(0)
    prev_bound = 0
    for tier in tiers:
        ub = tier.get("upper_bound_cents")
        band_top = H if ub is None else ub
        slice_width = min(H, band_top) - prev_bound
        if slice_width < 0:
            slice_width = 0
        premium_exact += Decimal(slice_width) * Decimal(tier["rate_bps"]) / Decimal(10000)
        prev_bound = band_top
        if H <= band_top:
            break
    return round_half_up(premium_exact)


def resale_royalty_cents(hammer_cents, artist_alive):
    """Droit de suite royalty: tiered marginal, summed exact, rounded once,
    then capped. Eligibility gated on artist_alive AND hammer >= floor.

    Returns (eligible, royalty_cents). When not eligible, eligible is False and
    royalty_cents is 0 (no row should be created by the caller)."""
    H = hammer_cents
    if not artist_alive or H < ROYALTY_FLOOR_CENTS:
        return False, 0
    royalty_exact = Decimal(0)
    prev_bound = 0
    for band_top, rate_bps in ROYALTY_BANDS:
        top = H if band_top is None else band_top
        slice_width = min(H, top) - prev_bound
        if slice_width < 0:
            slice_width = 0
        royalty_exact += Decimal(slice_width) * Decimal(rate_bps) / Decimal(10000)
        prev_bound = top
        if H <= top:
            break
    royalty_raw = round_half_up(royalty_exact)
    return True, min(royalty_raw, ROYALTY_CAP_CENTS)


def seller_commission_cents(hammer_cents, commission_bps):
    """round_half_up(H * commission_bps / 10000)."""
    exact = Decimal(hammer_cents) * Decimal(commission_bps) / Decimal(10000)
    return round_half_up(exact)


def increment_for_band(standing_high_cents):
    """Increment for the band the standing high sits in. Half-open [lo, hi)."""
    S = standing_high_cents
    for upper, inc in BID_BANDS:
        if upper is None:
            return inc
        if S < upper:
            return inc
    return BID_BANDS[-1][1]


def min_next_bid_cents(standing_high_cents):
    """Minimum acceptable amount for a new bid given the standing high.

    If standing high is 0 (no bids yet), the opening bid must be at least the
    starting floor (which equals max(STARTING_BID_FLOOR_CENTS, increment for
    band 0)). Otherwise it is standing_high + increment for its band.
    """
    S = standing_high_cents
    if S == 0:
        return max(STARTING_BID_FLOOR_CENTS, increment_for_band(0))
    return S + increment_for_band(S)
