"""Capital replacement forecast (capital_replacement_forecast, PRD §3.7)."""
from datetime import datetime, timezone

from db import store, now
from .core import add_months_date, add_years_dt

CONDITION_FACTOR_NUM_DEN = {
    1: (60, 100),
    2: (80, 100),
    3: (100, 100),
    4: (115, 100),
    5: (130, 100),
}


def _property_assets(property_id):
    out = []
    for a in store.assets.values():
        unit = store.units.get(a["unit_id"])
        if unit is None:
            continue
        building = store.buildings.get(unit["building_id"])
        if building is None or building["property_id"] != property_id:
            continue
        out.append(a)
    return out


def _effective_life_months(asset, variant):
    if variant == "AGE_BASED":
        return asset["expected_life_months"]
    # CONDITION_BASED: null condition_score maps to score 3 (factor 1.00)
    score = asset["condition_score"] if asset["condition_score"] is not None else 3
    num, den = CONDITION_FACTOR_NUM_DEN[score]
    return (asset["expected_life_months"] * num) // den  # floor to whole months


def compute_forecast(property_id, horizon_years, variant):
    clock = now()
    per_year = [0] * horizon_years
    count = 0
    for asset in _property_assets(property_id):
        if asset["operational_status"] == "DECOMMISSIONED":
            continue
        eff = _effective_life_months(asset, variant)
        repl_date = add_months_date(asset["_installed_dt"], eff)
        repl_dt = datetime(repl_date.year, repl_date.month, repl_date.day,
                           tzinfo=timezone.utc)
        if repl_dt < clock:
            bucket = 0
        else:
            bucket = None
            for y in range(horizon_years):
                lo = add_years_dt(clock, y)
                hi = add_years_dt(clock, y + 1)
                if lo <= repl_dt < hi:
                    bucket = y
                    break
        if bucket is None:
            continue
        per_year[bucket] += asset["replacement_cost_cents"]
        count += 1
    return {
        "per_year_cents": per_year,
        "total_projected_cents": sum(per_year),
        "asset_count_projected": count,
    }
