"""Market comparables valuation (PRD 3.2).

Input set: VERIFIED ComparableSales whose make AND model exactly equal the
listing's (exact string equality). Fewer than MIN_COMPARABLES ->
ERR_INSUFFICIENT_COMPARABLES (422).

PROVISIONAL: plain mean of sale_price_usd, rounded half-up to 2dp.
FINAL: per comp, factor = 1 - TIME_ADJ_PCT_PER_HOUR * (comp_hours -
listing_hours); adjusted price rounded half-up to 2dp FIRST, then averaged,
quotient rounded half-up to 2dp. The pinned nested rounding makes FINAL
diverge from PROVISIONAL on the same comp set.
"""
from decimal import Decimal, ROUND_HALF_UP

from errors import ERR_INSUFFICIENT_COMPARABLES, raise_error
from validate import CENT

MIN_COMPARABLES = 3
TIME_ADJ_PCT_PER_HOUR = Decimal("0.00004")


def _round2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def matching_verified_comps(listing, comps):
    return [
        c for c in comps
        if c["comp_status"] == "VERIFIED"
        and c["make"] == listing["make"]
        and c["model"] == listing["model"]
    ]


def run_valuation(listing, variant, comps):
    input_set = matching_verified_comps(listing, comps)
    if len(input_set) < MIN_COMPARABLES:
        raise_error(
            ERR_INSUFFICIENT_COMPARABLES,
            "fewer than 3 VERIFIED comparable sales exactly match the "
            "listing make and model",
        )
    count = len(input_set)
    if variant == "PROVISIONAL":
        total = sum((c["sale_price_usd"] for c in input_set), Decimal("0"))
        return _round2(total / count)
    # FINAL: per-comp time adjustment with per-line rounding before averaging
    adjusted = []
    for comp in input_set:
        factor = (
            Decimal(1)
            - TIME_ADJ_PCT_PER_HOUR
            * (comp["total_time_hours"] - listing["total_time_hours"])
        )
        adjusted.append(_round2(comp["sale_price_usd"] * factor))
    return _round2(sum(adjusted, Decimal("0")) / count)
