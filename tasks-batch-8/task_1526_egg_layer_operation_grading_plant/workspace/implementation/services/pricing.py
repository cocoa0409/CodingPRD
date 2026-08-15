"""Cost-per-dozen and feed-conversion calculations (PRD §3.3, scaffold §1.3)."""
from decimal import Decimal

from db import STORE, today
from errors import ApiError, ERR_VALIDATION, ERR_SETTLEMENT_EMPTY
from util import D, rhu, rhu_int
from services.domain import (
    AMORTIZATION_DAYS,
    STANDARD_FEED_G_PER_HEN_DAY,
    SIZE_COUNT_FIELD,
    SIZE_WEIGHT_G,
    farm_of_flock,
    flocks_of_farm,
    production_days_of_flock,
    dispositions_of_flock,
    grading_runs_of_flock,
    flock_current_hen_count,
    flock_age_weeks,
    lay_curve,
)


def _in_window(d, period_start, period_end):
    return period_start <= d <= period_end


def _window_days(flock_ids, period_start, period_end):
    return [
        p for p in STORE["production_days"].values()
        if p["flock_id"] in flock_ids and _in_window(p["lay_date"], period_start, period_end)
    ]


def _spent_hen_credit(flock_ids, period_start, period_end):
    total = 0
    for d in STORE["dispositions"].values():
        if d["flock_id"] in flock_ids and d["status"] == "COMPLETED" \
                and d.get("completed_date") is not None \
                and _in_window(d["completed_date"], period_start, period_end):
            total += d["revenue_cents"]
    return total


def _amortization(flock, days_in_period):
    return rhu_int(D(flock["pullet_cost_cents"]) * D(days_in_period) / D(AMORTIZATION_DAYS))


def _avg_egg_weight_g(flock):
    """60g default until a CONFIRMED non-voided grading run exists; then the
    size-weighted average over the most recently confirmed run's distribution."""
    confirmed = [
        g for g in grading_runs_of_flock(flock["id"]) if g["status"] == "CONFIRMED"
    ]
    if not confirmed:
        return D(60)
    latest = max(confirmed, key=lambda g: (g["_tick"], g["_seq"]))
    total_count = 0
    weighted = 0
    for size, field in SIZE_COUNT_FIELD.items():
        c = latest.get(field) or 0
        total_count += c
        weighted += c * SIZE_WEIGHT_G[size]
    if total_count == 0:
        return D(60)
    return D(weighted) / D(total_count)


def feed_conversion_ratio(flock, period_start, period_end):
    """FCR over inclusive window, 3dp round-half-up; null when egg mass is zero."""
    days = _window_days({flock["id"]}, period_start, period_end)
    total_feed_kg = sum(p["feed_issued_kg"] for p in days)
    total_eggs = sum(p["eggs_collected"] for p in days)
    avg_w = _avg_egg_weight_g(flock)
    egg_mass_kg = D(total_eggs) * avg_w / D(1000)
    if egg_mass_kg == 0:
        return None
    return float(rhu(D(total_feed_kg) / egg_mass_kg, 3))


def _overhead(farm, days_in_period, share):
    return rhu_int(D(farm["daily_overhead_cents"]) * D(days_in_period) * share)


def cost_per_dozen_actual(flock, farm, period_start, period_end, days_in_period):
    """ACTUAL_FIFO variant over the flock's own window (economics endpoint)."""
    days = _window_days({flock["id"]}, period_start, period_end)
    total_eggs = sum(p["eggs_collected"] for p in days)
    feed_cents = sum(p["feed_cost_cents"] for p in days)
    hen_days = sum(p["hens_at_start"] for p in days)
    farm_hen_days = sum(
        p["hens_at_start"]
        for p in _window_days({f["id"] for f in flocks_of_farm(farm["id"])},
                              period_start, period_end)
    )
    share = D(hen_days) / D(farm_hen_days) if farm_hen_days else D(0)
    overhead = _overhead(farm, days_in_period, share)
    amort = _amortization(flock, days_in_period)
    credit = _spent_hen_credit({flock["id"]}, period_start, period_end)
    if total_eggs == 0:
        raise ApiError(ERR_VALIDATION, 400, "No eggs collected in the period")
    cpd = rhu(D(feed_cents + overhead + amort - credit) * D(12) / D(total_eggs), 2)
    return {
        "cost_per_dozen_cents": float(cpd),
        "total_eggs": total_eggs,
        "feed_cost_cents": feed_cents,
        "overhead_cents": overhead,
        "amortization_cents": amort,
        "spent_hen_credit_cents": credit,
    }


def cost_per_dozen_projected(flock, farm, period_start, period_end, days_in_period):
    """PROJECTED_STANDARD variant: lay-curve eggs + 115 g/hen-day standard intake."""
    age_at_end = (period_end - flock["placement_date"]).days // 7
    rate = lay_curve(age_at_end, flock["lay_cycle"], flock["breed_peak_rate_pct"], flock["status"])
    hens = flock_current_hen_count(flock)
    projected_eggs = rhu_int(D(hens) * rate / D(100) * D(days_in_period))
    if projected_eggs == 0:
        raise ApiError(ERR_VALIDATION, 400, "Projected eggs are zero for the period")
    standard_feed_kg = D(hens * STANDARD_FEED_G_PER_HEN_DAY * days_in_period) / D(1000)
    deliveries = [d for d in STORE["feed_deliveries"].values() if d["farm_id"] == farm["id"]]
    if deliveries:
        latest = max(deliveries, key=lambda d: (d["delivered_at"], -d["_seq"]))
        latest_price = latest["cost_per_kg_cents"]
    else:
        latest_price = 0
    feed_cents = rhu_int(standard_feed_kg * D(latest_price))
    proj_hen_days = hens * days_in_period
    farm_proj = sum(
        flock_current_hen_count(f) * days_in_period for f in flocks_of_farm(farm["id"])
    )
    share = D(proj_hen_days) / D(farm_proj) if farm_proj else D(0)
    overhead = _overhead(farm, days_in_period, share)
    amort = _amortization(flock, days_in_period)
    credit = _spent_hen_credit({flock["id"]}, period_start, period_end)
    cpd = rhu(D(feed_cents + overhead + amort - credit) * D(12) / D(projected_eggs), 2)
    return {
        "cost_per_dozen_cents": float(cpd),
        "total_eggs": projected_eggs,
        "feed_cost_cents": feed_cents,
        "overhead_cents": overhead,
        "amortization_cents": amort,
        "spent_hen_credit_cents": credit,
    }


def farm_cost_per_dozen_actual(farm, period_start, period_end):
    """Farm-level ACTUAL_FIFO used by COST_PLUS settlement finalize (PRD §3.6).
    Returns Decimal cents-per-dozen (2dp). Zero eggs -> ERR_SETTLEMENT_EMPTY."""
    days_in_period = (period_end - period_start).days + 1
    flocks = flocks_of_farm(farm["id"])
    flock_ids = {f["id"] for f in flocks}
    days = _window_days(flock_ids, period_start, period_end)
    total_eggs = sum(p["eggs_collected"] for p in days)
    if total_eggs == 0:
        raise ApiError(ERR_SETTLEMENT_EMPTY, 422, "No eggs collected in the settlement period")
    feed_cents = sum(p["feed_cost_cents"] for p in days)
    overhead = _overhead(farm, days_in_period, D(1))  # farm-wide share is 1
    amort = sum(_amortization(f, days_in_period) for f in flocks)
    credit = _spent_hen_credit(flock_ids, period_start, period_end)
    return rhu(D(feed_cents + overhead + amort - credit) * D(12) / D(total_eggs), 2)
