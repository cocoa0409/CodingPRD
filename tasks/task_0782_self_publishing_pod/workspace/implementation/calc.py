"""Deterministic calculation rules (SCAFFOLD §1.3, PRD §2.5 / §3).

All monetary results are integer cents rounded half-up. Spine widths are mm to
2 dp, round half-up. Decimals are constructed from str() to avoid binary float
contamination.
"""
from decimal import Decimal, ROUND_HALF_UP

# ---- constants ----
MIN_PAGE_COUNT = 24
SPINE_TOLERANCE_MM = Decimal("0.5")
PRINT_FIXED_CHARGE_CENTS = Decimal("85")
PER_PAGE_RATE_CENTS = {
    "BW": Decimal("1.2"),
    "STANDARD_COLOR": Decimal("7.0"),
    "PREMIUM_COLOR": Decimal("10.0"),
}
LARGE_TRIM_SURCHARGE_CENTS_PER_PAGE = Decimal("0.5")
LARGE_TRIM_SIZES = {"7x10", "8.5x11"}
PAPER_CALIPER_MM = {
    "WHITE": Decimal("0.0572"),
    "CREAM": Decimal("0.0635"),
    "COLOR": Decimal("0.0572"),
}


def _d(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rhu_int(value):
    return int(_d(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_2dp(value):
    return _d(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def print_cost_per_unit(page_count, interior_color, trim_size):
    """Format.print_cost_cents (PRINT only). Returns integer cents."""
    base_rate = PER_PAGE_RATE_CENTS[interior_color]
    surcharge = (LARGE_TRIM_SURCHARGE_CENTS_PER_PAGE
                 if trim_size in LARGE_TRIM_SIZES else Decimal("0"))
    pages = _d(page_count)
    total = PRINT_FIXED_CHARGE_CENTS + pages * base_rate + pages * surcharge
    return rhu_int(total)


def cover_spine_width(page_count, paper_type):
    """Asset.spine_width_mm (COVER only). Returns a Decimal (2 dp)."""
    caliper = PAPER_CALIPER_MM[paper_type]
    return rhu_2dp(_d(page_count) * caliper)


def royalty_per_unit(fmt, channel, list_price_cents, expanded_reach):
    """ChannelPrice.royalty_per_unit_cents snapshot. Returns integer cents."""
    lp = _d(list_price_cents)
    if fmt["format_type"] == "PRINT":
        disc = (_d(channel["distribution_discount_expanded"]) if expanded_reach
                else _d(channel["distribution_discount_standard"]))
        print_cost = _d(fmt.get("print_cost_cents") or 0)
        return rhu_int(lp * (Decimal("1") - disc) - print_cost)
    # EBOOK
    low = channel.get("ebook_rate_low_threshold_cents")
    high = channel.get("ebook_rate_high_threshold_cents")
    in_band = (low is not None and high is not None
               and low <= list_price_cents <= high)
    if in_band:
        rate = _d(channel["ebook_high_rate"])
        fee_per_mb = _d(channel.get("delivery_fee_per_mb_cents") or 0)
        delivery_fee = rhu_int(_d(fmt.get("file_size_mb") or 0) * fee_per_mb)
    else:
        rate = _d(channel["ebook_low_rate"])
        delivery_fee = 0
    return rhu_int(lp * rate - _d(delivery_fee))


def sales_line_amounts(royalty_per_unit_cents, units, line_type, returns_reserve_pct):
    """Returns (gross_royalty_cents, reserve_held_cents)."""
    magnitude = royalty_per_unit_cents * units
    reserve = rhu_int(_d(magnitude) * _d(returns_reserve_pct))
    if line_type == "SALE":
        return magnitude, reserve
    return -magnitude, -reserve
