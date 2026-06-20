"""Calculation primitives — rounding disciplines per PRD 2.6.

All monetary math uses Decimal with explicit rounding modes; never float.

PRD 2.6 rounding disciplines (part of the contract per calculation):
  - round half up : securities valuation, pool-allocation value, per-allocation admin fee
  - floor         : crypto valuation, pool units BOUGHT
  - ceiling       : pool units SURRENDERED on a redemption
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

MICRO = 1_000_000          # units scale (units_micro = real units * 1,000,000)
MILLI = 1000               # quantity scale (quantity_milli = real quantity * 1000)
BPS_SCALE = 10000          # basis-point scale
QUARTERS = 4               # quarters in a year
FEE_DIVISOR = BPS_SCALE * QUARTERS   # 40000


def round_half_up(value):
    """Round a Decimal to the nearest integer, exact halves going up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def ceil_div(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


def allocation_value_cents(units_micro, nav_per_unit_cents):
    """Value a single allocation: units_micro / 1e6 * nav, round half up (PRD 3.4)."""
    if units_micro <= 0:
        return 0
    raw = Decimal(units_micro) / Decimal(MICRO) * Decimal(nav_per_unit_cents)
    return round_half_up(raw)


def units_bought_micro(amount_cents, nav_per_unit_cents):
    """BUY: floor(amount_cents * 1e6 / nav) (PRD 3.4 — never credit a fractional unit)."""
    raw = Decimal(amount_cents) * Decimal(MICRO) / Decimal(nav_per_unit_cents)
    return floor_div(raw)


def units_redeemed_micro(amount_cents, nav_per_unit_cents):
    """REDEEM: ceil(amount_cents * 1e6 / nav) (PRD 3.4 — surrender enough to cover cash)."""
    raw = Decimal(amount_cents) * Decimal(MICRO) / Decimal(nav_per_unit_cents)
    return ceil_div(raw)


def contribution_fmv(contribution):
    """Fair-market value per PRD 3.3 / SCAFFOLD contribution_fair_market_value.

    Assumes required pricing inputs are present (validated by the caller).
    """
    asset_type = contribution["asset_type"]
    if asset_type == "CASH":
        return int(contribution["cash_amount_cents"])
    if asset_type == "SECURITIES":
        shares = Decimal(contribution["quantity_milli"]) / Decimal(MILLI)
        if contribution.get("thinly_traded"):
            # CLOSING_PRICE variant
            raw = shares * Decimal(contribution["closing_price_cents"])
        else:
            # MEAN_HIGH_LOW variant: shares * (high + low) / 2
            mean = (Decimal(contribution["high_price_cents"])
                    + Decimal(contribution["low_price_cents"])) / Decimal(2)
            raw = shares * mean
        return round_half_up(raw)
    if asset_type == "CRYPTO":
        qty = Decimal(contribution["quantity_milli"]) / Decimal(MILLI)
        raw = qty * Decimal(contribution["spot_price_cents"])
        return floor_div(raw)
    return 0


def per_allocation_quarterly_fee(invested_value_cents, fee_bps):
    """Per-allocation quarterly admin fee (PRD 3.7 / quarterly_admin_fee).

    fee = round_half_up(fee_bps * invested_value / 40000). Rounding happens per
    allocation BEFORE summing (pinned order).
    """
    raw = Decimal(fee_bps) * Decimal(invested_value_cents) / Decimal(FEE_DIVISOR)
    return round_half_up(raw)
