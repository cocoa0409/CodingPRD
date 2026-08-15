"""PerformanceYear endpoints and the year lifecycle state machine."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_DISPUTE_WINDOW_OPEN,
    ERR_DUPLICATE_YEAR_LABEL,
    ERR_EMPTY_POPULATION,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MEASUREMENT_PERIOD_NOT_ENDED,
    ERR_NO_LOCKED_ATTRIBUTION_RUN,
    ERR_NOT_FOUND,
    ERR_PERIOD_OVERLAP,
    ERR_QUALITY_RESULTS_UNLOCKED,
    ERR_SETTLEMENT_BEYOND_PROVISIONAL,
    ERR_SETTLEMENT_NOT_DISTRIBUTED,
    ERR_SETTLEMENT_NOT_FINAL,
    ERR_YEAR_OUTSIDE_TERM,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import calculations as calc
from services import engine
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    reject_unknown_fields,
    require_date,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("performance_years", __name__)


@bp.route("/vbc/performance-years", methods=["POST"])
@require_roles("PayerAdmin")
def create_year(_user_id: str, _role: str):
    body = get_json_body()
    raw_contract = body.get("contract_id")
    if isinstance(raw_contract, str) and raw_contract != "" and raw_contract not in db.contracts:
        raise_err(ERR_NOT_FOUND, "contract_id does not exist")
    reject_unknown_fields(body, {"contract_id", "year_label", "period_start", "period_end"})
    contract_id = require_string(body, "contract_id")
    year_label = require_int(body, "year_label")
    period_start = require_date(body, "period_start")
    period_end = require_date(body, "period_end")
    if contract_id not in db.contracts:
        raise_err(ERR_NOT_FOUND, "contract_id does not exist")

    start = db.parse_date(period_start)
    end = db.parse_date(period_end)

    # Priority 9 (overlap, half-open windows; adjacency allowed) before
    # priority 11 (year_label uniqueness) before priority 12 (date range).
    if start < end:
        for year in db.performance_years.values():
            if year["contract_id"] != contract_id:
                continue
            other_start = db.parse_date(year["period_start"])
            other_end = db.parse_date(year["period_end"])
            if start < other_end and end > other_start:
                raise_err(ERR_PERIOD_OVERLAP, "Year window intersects an existing year of the contract")

    for year in db.performance_years.values():
        if year["contract_id"] == contract_id and year["year_label"] == year_label:
            raise_err(ERR_DUPLICATE_YEAR_LABEL, "year_label already exists on the contract")

    if start >= end:
        raise_err(ERR_INVALID_DATE_RANGE, "period_start must be before period_end")

    year = {
        "contract_id": contract_id,
        "year_label": year_label,
        "period_start": period_start,
        "period_end": period_end,
        "year_status": "SETUP",
        "total_member_months": 0,
        "actual_cost_cents": 0,
        "benchmark_cost_cents": 0,
        "risk_adjustment_factor_milli": None,
        "withhold_pool_cents": 0,
        "accrued_reserve_cents": 0,
        "locked_run_id": None,
    }
    db.stamp_new(year)
    db.performance_years[year["id"]] = year
    return success_object(year, 201)


@bp.route("/vbc/performance-years", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_years(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.performance_years.values()))
    items = apply_filters(items, ["contract_id", "locked_run_id", "year_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


def _get_year_or_404(year_id: str) -> dict:
    year = db.performance_years.get(year_id)
    if year is None:
        raise_err(ERR_NOT_FOUND, "PerformanceYear id does not exist")
    return year


@bp.route("/vbc/performance-years/<year_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_year(year_id: str, _user_id: str, _role: str):
    return success_object(_get_year_or_404(year_id))


@bp.route("/vbc/performance-years/<year_id>/open-attribution", methods=["POST"])
@require_roles("PayerAdmin")
def open_attribution(year_id: str, _user_id: str, _role: str):
    year = _get_year_or_404(year_id)
    # Priority 6 (state) before priority 8 (temporal window-in-term).
    if year["year_status"] != "SETUP":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a SETUP year can open attribution")
    contract = engine.contract_of_year(year)
    if contract is None or contract["contract_status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "Contract must be ACTIVE to open attribution")
    if (
        db.parse_date(year["period_start"]) < db.parse_date(contract["effective_start"])
        or db.parse_date(year["period_end"]) > db.parse_date(contract["effective_end"])
    ):
        raise_err(ERR_YEAR_OUTSIDE_TERM, "Year window must be contained in the contract term")
    year["year_status"] = "ATTRIBUTION_OPEN"
    db.touch(year)
    return success_object(year)


@bp.route("/vbc/performance-years/<year_id>/lock-attribution", methods=["POST"])
@require_roles("PayerAdmin")
def lock_attribution(year_id: str, _user_id: str, _role: str):
    year = _get_year_or_404(year_id)
    if year["year_status"] != "ATTRIBUTION_OPEN":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ATTRIBUTION_OPEN year can lock attribution")
    locked_runs = [
        r for r in db.attribution_runs.values()
        if r["performance_year_id"] == year_id and r["run_status"] == "LOCKED"
    ]
    if not locked_runs:
        raise_err(ERR_NO_LOCKED_ATTRIBUTION_RUN, "No LOCKED attribution run exists for the year")
    run = locked_runs[0]
    year["locked_run_id"] = run["id"]
    # Rollup folded into the transition: the year's version advances by
    # exactly 1 for the whole operation (PRD §3.4).
    contract = engine.contract_of_year(year)
    for key, value in calc.compute_attribution_rollup(contract, year).items():
        year[key] = value
    year["year_status"] = "ATTRIBUTION_LOCKED"
    db.touch(year)
    return success_object(year)


@bp.route("/vbc/performance-years/<year_id>/begin-measurement", methods=["POST"])
@require_roles("PayerAdmin")
def begin_measurement(year_id: str, _user_id: str, _role: str):
    year = _get_year_or_404(year_id)
    if year["year_status"] != "ATTRIBUTION_LOCKED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ATTRIBUTION_LOCKED year can begin measurement")
    contract = engine.contract_of_year(year)
    for key, value in calc.compute_cost_and_pool(contract, year).items():
        year[key] = value
    year["year_status"] = "MEASURING"
    db.touch(year)
    return success_object(year)


@bp.route("/vbc/performance-years/<year_id>/begin-reconciliation", methods=["POST"])
@require_roles("PayerAdmin")
def begin_reconciliation(year_id: str, _user_id: str, _role: str):
    year = _get_year_or_404(year_id)
    if year["year_status"] != "MEASURING":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a MEASURING year can begin reconciliation")
    # Temporal (8), then aggregate guards in the scaffold's declared order.
    if db.clock_date() < db.parse_date(year["period_end"]):
        raise_err(ERR_MEASUREMENT_PERIOD_NOT_ENDED, "Measurement period has not ended on the logical clock")
    if year["total_member_months"] <= 0:
        raise_err(ERR_EMPTY_POPULATION, "total_member_months must be > 0 to begin reconciliation")
    for result in db.quality_results.values():
        if (
            result["performance_year_id"] == year_id
            and result["result_status"] not in ("LOCKED", "EXCLUDED")
        ):
            raise_err(ERR_QUALITY_RESULTS_UNLOCKED, "Every quality result must be LOCKED or EXCLUDED")
    year["year_status"] = "RECONCILING"
    db.touch(year)
    return success_object(year)


@bp.route("/vbc/performance-years/<year_id>/reopen-attribution", methods=["POST"])
@require_roles("PayerAdmin")
def reopen_attribution(year_id: str, _user_id: str, _role: str):
    year = _get_year_or_404(year_id)
    if year["year_status"] != "RECONCILING":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a RECONCILING year can reopen attribution")
    settlement = engine.active_settlement_of_year(year_id)
    if settlement is not None and settlement["settlement_status"] != "PROVISIONAL":
        raise_err(ERR_SETTLEMENT_BEYOND_PROVISIONAL, "Settlement has advanced beyond PROVISIONAL")

    # Coordinated reset: LOCKED run -> SUPERSEDED; PROVISIONAL settlement ->
    # VOID; rollups zeroed; locked_run_id cleared.
    locked_run_id = year.get("locked_run_id")
    if locked_run_id is not None:
        run = db.attribution_runs.get(locked_run_id)
        if run is not None and run["run_status"] == "LOCKED":
            db.apply_updates(run, {"run_status": "SUPERSEDED"})
    if settlement is not None:
        db.apply_updates(settlement, {"settlement_status": "VOID"})

    year["locked_run_id"] = None
    year["total_member_months"] = 0
    year["benchmark_cost_cents"] = 0
    year["risk_adjustment_factor_milli"] = None
    year["actual_cost_cents"] = 0
    year["withhold_pool_cents"] = 0
    year["year_status"] = "ATTRIBUTION_OPEN"
    db.touch(year)
    return success_object(year)


@bp.route("/vbc/performance-years/<year_id>/mark-settled", methods=["POST"])
@require_roles("SettlementOfficer")
def mark_settled(year_id: str, _user_id: str, _role: str):
    year = _get_year_or_404(year_id)
    if year["year_status"] != "RECONCILING":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a RECONCILING year can be marked settled")
    # Priority 6 (state) before priority 8 (temporal dispute window).
    settlement = engine.active_settlement_of_year(year_id)
    if settlement is None or settlement["settlement_status"] not in ("FINALIZED", "AUTHORIZED", "DISTRIBUTED"):
        raise_err(ERR_SETTLEMENT_NOT_FINAL, "Settlement must be FINALIZED, AUTHORIZED, or DISTRIBUTED")
    window_end = db.add_days(db.parse_date(settlement["finalized_on"]), calc.DISPUTE_WINDOW_DAYS)
    if db.clock_date() <= window_end:
        raise_err(ERR_DISPUTE_WINDOW_OPEN, "Dispute window is still open")
    year["year_status"] = "SETTLED"
    year["accrued_reserve_cents"] = 0
    db.touch(year)
    return success_object(year)


@bp.route("/vbc/performance-years/<year_id>/close", methods=["POST"])
@require_roles("Auditor")
def close_year(year_id: str, _user_id: str, _role: str):
    year = _get_year_or_404(year_id)
    if year["year_status"] != "SETTLED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a SETTLED year can be closed")
    settlement = engine.active_settlement_of_year(year_id)
    if settlement is None or settlement["settlement_status"] != "DISTRIBUTED":
        raise_err(ERR_SETTLEMENT_NOT_DISTRIBUTED, "Settlement must be DISTRIBUTED to close the year")
    year["year_status"] = "CLOSED"
    db.touch(year)
    return success_object(year)
