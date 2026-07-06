"""Pricing / allocation calculations (PRD §3.3, §3.4, §3.5, §3.7, §3.10)."""
from decimal import Decimal, ROUND_HALF_UP

import constants as C


def _q2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q0(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def per_area_weekly_hours(area):
    """Raw (unrounded) weekly hours for one ServiceArea."""
    rate = C.PROD_RATE[area["soil_level"]]
    return Decimal(area["sqft"]) / rate * Decimal(area["frequency_per_week"])


def area_weekly_hours_display(area, loading_method):
    """The stored read-only weekly_hours for a ServiceArea, rounded per loading method.

    ESTIMATE rounds per-area to 2dp; LOADED keeps raw per-area (rounded only at the
    weekly sum). For the per-area display field we still expose 2dp under both methods,
    since the divergence the PRD pins is in the aggregate, not the per-row display.
    """
    return _q2(per_area_weekly_hours(area))


def labor_load(areas, loading_method):
    """Return monthly_labor_hours (Decimal, 2dp) for the given ServiceArea set."""
    if loading_method == "ESTIMATE":
        # round-then-sum
        weekly_total = sum((_q2(per_area_weekly_hours(a)) for a in areas), Decimal("0"))
    else:
        # LOADED: sum-then-round
        raw = sum((per_area_weekly_hours(a) for a in areas), Decimal("0"))
        weekly_total = _q2(raw)
    monthly = _q2(weekly_total * C.WEEKS_PER_MONTH)
    return monthly


def _burden(monthly_labor_hours):
    mh = monthly_labor_hours
    if mh <= C.BURDEN_BREAK_1:
        return C.BURDEN_T1
    if mh <= C.BURDEN_BREAK_2:
        return C.BURDEN_T2
    return C.BURDEN_T3


def bid_buildup(areas, base_wage_cents, target_margin_pct, loading_method):
    """Compute every monetary field for a BidEstimate. Returns a dict of ints/floats."""
    monthly = labor_load(areas, loading_method)

    burden = _burden(monthly)
    loaded_wage_cents = _q0(Decimal(base_wage_cents) * burden)
    labor_cost_cents = _q0(monthly * Decimal(loaded_wage_cents))

    supply_cost_cents = _q0(sum(
        (Decimal(a["sqft"]) * C.SUPPLY_RATE_CENTS_PER_SQFT[a["soil_level"]] for a in areas),
        Decimal("0"),
    ))

    direct_cost_cents = labor_cost_cents + supply_cost_cents + C.EQUIP_AMORT_CENTS
    overhead_cents = _q0(Decimal(direct_cost_cents) * C.OVERHEAD_PCT)
    total_cost_cents = direct_cost_cents + overhead_cents

    margin = Decimal(str(target_margin_pct))
    base_bid_cents = _q0(Decimal(total_cost_cents) / (Decimal("1") - margin))

    return {
        "monthly_labor_hours": float(monthly),
        "labor_cost_cents": labor_cost_cents,
        "supply_cost_cents": supply_cost_cents,
        "total_cost_cents": total_cost_cents,
        "base_bid_cents": base_bid_cents,
    }


def proposal_pricing(base_bid_cents, total_cost_cents):
    """Volume discount keyed on base_bid tier, then margin recomputed on discounted price.

    Returns (monthly_price_cents:int, achieved_margin_pct:float[2dp]).
    """
    bb = Decimal(base_bid_cents)
    if base_bid_cents < C.DISCOUNT_BREAK_1_CENTS:
        discount = Decimal("0.00")
    elif base_bid_cents < C.DISCOUNT_BREAK_2_CENTS:
        discount = C.DISCOUNT_T1_PCT
    else:
        discount = C.DISCOUNT_T2_PCT

    monthly_price_cents = _q0(bb * (Decimal("1") - discount))
    ratio = (Decimal(monthly_price_cents) - Decimal(total_cost_cents)) / Decimal(monthly_price_cents)
    pct = (ratio * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return monthly_price_cents, float(pct)


def renewal_escalation(base_monthly_cents, method):
    if method == "CPI":
        return _q0(Decimal(base_monthly_cents) * (Decimal("1") + C.CPI_PCT))
    return base_monthly_cents + C.FLAT_INCREASE_CENTS


def allocated_hours(shifts):
    """Sum of ASSIGNED shift_hours, accumulated in created order, rounded 2dp."""
    ordered = sorted([s for s in shifts if s["status"] == "ASSIGNED"], key=lambda s: s["_seq"])
    total = sum((Decimal(str(s["shift_hours"])) for s in ordered), Decimal("0"))
    return float(_q2(total))
