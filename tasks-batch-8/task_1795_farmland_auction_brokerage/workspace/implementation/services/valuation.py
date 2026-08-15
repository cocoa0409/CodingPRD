"""spi_adjusted_valuation: soil-adjusted comparable valuation per tract."""

import calendar
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import raise_err, ERR_NO_COMPARABLES

COMP_WINDOW_MONTHS = 24
RECENCY_WINDOW_MONTHS = 12
RECENCY_DISCOUNT = Decimal("0.97")
TILLABLE_BASE = Decimal("0.85")
TILLABLE_SLOPE = Decimal("0.30")

Q2 = Decimal("0.01")
Q0 = Decimal("1")


def sub_months(dt: datetime, months: int) -> datetime:
    """Calendar-month subtraction with day clamping, preserving time of day."""
    total = dt.year * 12 + (dt.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def comparable_set(listing):
    """ComparableSale rows matching the listing's state_code whose sale_date is in
    the inclusive trailing 24-month window [clock - 24 months, clock]."""
    now = db.clock_now()
    lo = sub_months(now, COMP_WINDOW_MONTHS)
    out = []
    for c in db.comparables.values():
        if c["state_code"] != listing["state_code"]:
            continue
        if lo <= c["_sale_date_dt"] <= now:
            out.append(c)
    return out


def compute_valuation(tract, variant):
    """Returns (comparable_count, value_per_acre Decimal, estimated_value Decimal).

    estimated_value: round half-up to whole dollars; value_per_acre: 2dp half-up.
    """
    listing = db.listings[tract["listing_id"]]
    comps = comparable_set(listing)
    if not comps:
        raise_err(ERR_NO_COMPARABLES, "no comparable sales in the trailing 24-month window")

    bases = []
    for c in comps:
        base = (c["sale_price_total"] / c["gross_acres"]) * (
            tract["soil_productivity_index"] / c["soil_productivity_index"]
        )
        bases.append(base)

    if variant == "PROVISIONAL":
        mean = sum(bases) / Decimal(len(bases))
    else:  # APPRAISAL
        now = db.clock_now()
        recency_cutoff = sub_months(now, RECENCY_WINDOW_MONTHS)
        tillable_factor = TILLABLE_BASE + TILLABLE_SLOPE * (
            tract["tillable_acres"] / tract["gross_acres"]
        )
        adjs = []
        for c, base in zip(comps, bases):
            recency = Decimal("1.0") if c["_sale_date_dt"] >= recency_cutoff else RECENCY_DISCOUNT
            adjs.append(base * tillable_factor * recency)
        mean = sum(adjs) / Decimal(len(adjs))

    estimated = (mean * tract["gross_acres"]).quantize(Q0, rounding=ROUND_HALF_UP)
    vpa = mean.quantize(Q2, rounding=ROUND_HALF_UP)
    return len(comps), vpa, estimated
