"""Cross-aggregate cascade engine (PRD §2.5, §2.10).

Every helper applies the conditional-bump rule of §2.5: a cascade target's
updated_at/version advance only when a field value actually changes. Direct
operator-driven transitions on the targeted resource always bump exactly once.
"""

from __future__ import annotations

import db
from services import calculations as calc


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def year_of(entity: dict, key: str = "performance_year_id") -> dict | None:
    return db.performance_years.get(entity.get(key))


def contract_of_year(year: dict) -> dict | None:
    return db.contracts.get(year["contract_id"])


def active_settlement_of_year(year_id: str) -> dict | None:
    """The year's at-most-one non-VOID settlement."""
    for s in db.settlements.values():
        if s["performance_year_id"] == year_id and s["settlement_status"] != "VOID":
            return s
    return None


# ---------------------------------------------------------------------------
# Cascade primitives
# ---------------------------------------------------------------------------

def flag_settlement_needs_recompute(year_id: str) -> None:
    """§2.10: post-finalize data mutations flag the year's settlement when it
    is in PROVISIONAL or FINALIZED. Past FINALIZED the flag is not consulted."""
    settlement = active_settlement_of_year(year_id)
    if settlement is None:
        return
    if settlement["settlement_status"] in ("PROVISIONAL", "FINALIZED"):
        db.apply_updates(settlement, {"needs_recompute": True})


def stale_published_reports(year_id: str) -> None:
    """Every PUBLISHED InterimReport of the year -> STALE. The year's
    accrued_reserve_cents is NOT retroactively adjusted."""
    for report in db.interim_reports.values():
        if report["performance_year_id"] == year_id and report["report_status"] == "PUBLISHED":
            db.apply_updates(report, {"report_status": "STALE"})


def recompute_attribution_rollup(year: dict) -> None:
    """attribution_rollup: total_member_months, risk_adjustment_factor_milli,
    benchmark_cost_cents from the LOCKED run's CONFIRMED population."""
    contract = contract_of_year(year)
    values = calc.compute_attribution_rollup(contract, year)
    db.apply_updates(year, values)


def recompute_cost(year: dict) -> None:
    """cost_measurement + withhold_pool from current PAID claims."""
    contract = contract_of_year(year)
    values = calc.compute_cost_and_pool(contract, year)
    db.apply_updates(year, values)


def after_population_mutation(year: dict) -> None:
    """Attribution exclude/reinstate and risk-score finalize/supersede:
    recompute the population rollups (only once attribution has been locked,
    i.e. locked_run_id set), stale published reports, flag the settlement."""
    if year.get("locked_run_id") is not None:
        recompute_attribution_rollup(year)
        stale_published_reports(year["id"])
    flag_settlement_needs_recompute(year["id"])


def after_cost_mutation(year: dict) -> None:
    """Claim mark-paid/void when the year is past MEASURING (RECONCILING or
    later): recompute cost rollups, stale published reports, flag settlement."""
    recompute_cost(year)
    stale_published_reports(year["id"])
    flag_settlement_needs_recompute(year["id"])


def recompute_settlement_fields(settlement: dict, recompute_year_cost: bool) -> None:
    """The full settlement chain against current data. On
    finalize/recalculate/auto-recalc the year's actual_cost_cents and
    withhold_pool_cents are recomputed first (cost_measurement trigger)."""
    year = db.performance_years[settlement["performance_year_id"]]
    contract = contract_of_year(year)
    if recompute_year_cost:
        recompute_cost(year)
    values = calc.compute_settlement_chain(contract, year, settlement)
    for key, value in values.items():
        settlement[key] = value
