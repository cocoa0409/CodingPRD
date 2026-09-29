"""Trade areas, the branch register, performance snapshots and on-demand scoring."""
from flask import Blueprint

import calc
import services as svc
from core import (DB, all_of, fail, new_record, public, touch, object_response,
                  list_response)
from validation import (authorize, require_branch_ownership, json_body, pagination,
                        filter_value, window, req_int, req_str, req_enum, req_date)

bp = Blueprint("network", __name__)

READ_ALL = ("NetworkStrategist", "ConsolidationApprover", "ComplianceOfficer", "HRPartner",
            "RealEstateManager", "NetworkOpsAdmin", "BranchManager")
READ_SNAPSHOT = ("NetworkStrategist", "ConsolidationApprover", "ComplianceOfficer",
                 "NetworkOpsAdmin", "BranchManager")
REGISTRARS = ("NetworkStrategist", "NetworkOpsAdmin")

SATURATION_TIERS = ("OVER_BRANCHED", "SATURATED", "UNDER_BRANCHED")
BRANCH_TYPES = ("FULL_SERVICE", "LIMITED_SERVICE", "DRIVE_UP")
TENURE_CLASSES = ("LEASED", "OWNED")
BRANCH_STATUSES = ("ACTIVE", "UNDER_REVIEW", "CLOSURE_SCHEDULED", "CLOSED", "DE_NOVO_RAMPING")
PERFORMANCE_BANDS = ("CORE", "STABLE", "WATCH", "CONSOLIDATION_CANDIDATE", "UNSCORED")
SNAPSHOT_BANDS = ("CORE", "STABLE", "WATCH", "CONSOLIDATION_CANDIDATE")
SCORING_VARIANTS = ("POINT_IN_TIME", "TRAILING_BLEND")


# --------------------------------------------------------------------------- #
# Trade areas
# --------------------------------------------------------------------------- #
@bp.post("/distribution/market-areas")
def create_market_area():
    authorize(REGISTRARS)
    body = json_body()
    name = req_str(body, "name", min_len=1, max_len=120)
    region_code = req_str(body, "region_code", pattern=r"[A-Z]{2}-[0-9]{2}")
    population = req_int(body, "population", minimum=1000)
    median_income = req_int(body, "median_household_income_cents", minimum=0)
    deposit_total = req_int(body, "deposit_market_total_cents", minimum=0)
    competitors = req_int(body, "competitor_branch_count", minimum=0)
    growth = req_int(body, "household_growth_pct_bps", minimum=-2000, maximum=5000)
    digital = req_int(body, "digital_penetration_bps", minimum=0, maximum=10000)

    for m in all_of("market_areas"):
        if m["region_code"] == region_code and m["name"] == name:
            fail("ERR_DUPLICATE_KEY",
                 "A trade area named '%s' already exists in region %s." % (name, region_code))

    density = calc.branch_density_per_100k(0, competitors, population)
    rec = new_record("market_areas", {
        "name": name,
        "region_code": region_code,
        "population": population,
        "median_household_income_cents": median_income,
        "deposit_market_total_cents": deposit_total,
        "competitor_branch_count": competitors,
        "household_growth_pct_bps": growth,
        "digital_penetration_bps": digital,
        "competitor_density_index": calc.competitor_density_index(competitors, population),
        "own_branch_count": 0,
        "branch_density_per_100k": density,
        "saturation_tier": calc.saturation_tier(density),
        "absorbed_deposits_cents": 0,
        "cumulative_runoff_deposits_cents": 0,
        "flagged_case_count": 0,
        "remediation_case_count": 0,
        "de_novo_hold": False,
    })
    return object_response(public(rec), 201)


@bp.get("/distribution/market-areas/<market_area_id>")
def read_market_area(market_area_id):
    authorize(READ_ALL)
    rec = svc.path_lookup("market_areas", market_area_id, "Market area")
    return object_response(public(rec))


@bp.get("/distribution/market-areas")
def list_market_areas():
    authorize(READ_ALL)
    limit, offset = pagination()
    region_code = filter_value("region_code")
    tier = filter_value("saturation_tier", SATURATION_TIERS)
    rows = all_of("market_areas")
    if region_code is not None:
        rows = [r for r in rows if r["region_code"] == region_code]
    if tier is not None:
        rows = [r for r in rows if r["saturation_tier"] == tier]
    rows = svc.oldest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------- #
# Branch register
# --------------------------------------------------------------------------- #
@bp.post("/distribution/branches")
def create_branch():
    authorize(REGISTRARS)
    body = json_body()
    market_area_id = req_str(body, "market_area_id")
    branch_code = req_str(body, "branch_code", pattern=r"[A-Z]{2}-[0-9]{3}")
    branch_type = req_enum(body, "branch_type", BRANCH_TYPES)
    tenure_class = req_enum(body, "tenure_class", TENURE_CLASSES)
    deposit_balance = req_int(body, "deposit_balance_cents", minimum=0)
    txn_count = req_int(body, "monthly_transaction_count", minimum=0)
    digital = req_int(body, "digital_adoption_bps", minimum=0, maximum=10000)
    expense = req_int(body, "annual_noninterest_expense_cents", minimum=0)
    revenue = req_int(body, "annual_revenue_cents", minimum=0)
    fte = req_int(body, "fte_count", minimum=0)
    atm = req_int(body, "atm_count", minimum=0)
    opened_on = req_date(body, "opened_on")
    variant = req_enum(body, "scoring_variant", SCORING_VARIANTS, required=False,
                       default="TRAILING_BLEND")
    capacity = req_int(body, "onboarding_capacity_households_per_day", minimum=1,
                       required=False, default=40)

    market = svc.ref_lookup("market_areas", market_area_id, "market area")

    for b in all_of("branches"):
        if b["branch_code"] == branch_code:
            fail("ERR_DUPLICATE_KEY", "Branch code '%s' is already in use." % branch_code)

    rec = new_record("branches", {
        "market_area_id": market_area_id,
        "branch_code": branch_code,
        "branch_type": branch_type,
        "tenure_class": tenure_class,
        "status": "ACTIVE",
        "deposit_balance_cents": deposit_balance,
        "monthly_transaction_count": txn_count,
        "digital_adoption_bps": digital,
        "annual_noninterest_expense_cents": expense,
        "annual_revenue_cents": revenue,
        "fte_count": fte,
        "atm_count": atm,
        "opened_on": opened_on,
        "scoring_variant": variant,
        "onboarding_capacity_households_per_day": capacity,
        "absorbing_branch_id": None,
        "performance_score_bps": None,
        "performance_band": "UNSCORED",
        "snapshot_count": 0,
        "pre_close_deposits_cents": None,
        "pre_close_fte_count": None,
        "transferred_in_deposits_cents": 0,
    })
    svc.refresh_market_footprint(market)
    return object_response(public(rec), 201)


@bp.get("/distribution/branches/<branch_id>")
def read_branch(branch_id):
    authorize(READ_ALL)
    rec = svc.path_lookup("branches", branch_id, "Branch")
    return object_response(public(rec))


@bp.get("/distribution/branches")
def list_branches():
    authorize(READ_ALL)
    limit, offset = pagination()
    market_area_id = filter_value("market_area_id")
    absorbing_branch_id = filter_value("absorbing_branch_id")
    status = filter_value("status", BRANCH_STATUSES)
    band = filter_value("performance_band", PERFORMANCE_BANDS)
    rows = all_of("branches")
    if market_area_id is not None:
        rows = [r for r in rows if r["market_area_id"] == market_area_id]
    if absorbing_branch_id is not None:
        rows = [r for r in rows if r["absorbing_branch_id"] == absorbing_branch_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if band is not None:
        rows = [r for r in rows if r["performance_band"] == band]
    rows = svc.oldest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------- #
# Performance snapshots
# --------------------------------------------------------------------------- #
@bp.post("/distribution/branches/<branch_id>/performance-snapshots")
def create_snapshot(branch_id):
    user_id, role = authorize(("NetworkStrategist", "BranchManager"))
    require_branch_ownership(user_id, role, branch_id)
    body = json_body()
    period_label = req_str(body, "period_label", min_len=1, max_len=20)
    period_end_date = req_date(body, "period_end_date")
    deposits = req_int(body, "deposits_cents", minimum=0)
    txn = req_int(body, "transaction_count", minimum=0)
    digital_active = req_int(body, "digital_active_bps", minimum=0, maximum=10000)
    revenue = req_int(body, "revenue_cents", minimum=0)
    expense = req_int(body, "noninterest_expense_cents", minimum=0)

    branch = svc.path_lookup("branches", branch_id, "Branch")

    for s in all_of("performance_snapshots"):
        if s["branch_id"] == branch_id and s["period_label"] == period_label:
            fail("ERR_DUPLICATE_KEY",
                 "Period '%s' has already been recorded for this branch." % period_label)

    deposit_bps = calc.deposit_factor_bps(deposits)
    txn_bps = calc.transaction_factor_bps(txn)
    digital_bps = calc.digital_factor_bps(digital_active)
    profit_bps = calc.profitability_factor_bps(revenue, expense)
    composite = calc.composite_score_bps(deposit_bps, txn_bps, digital_bps, profit_bps)

    rec = new_record("performance_snapshots", {
        "branch_id": branch_id,
        "period_label": period_label,
        "period_end_date": period_end_date,
        "deposits_cents": deposits,
        "transaction_count": txn,
        "digital_active_bps": digital_active,
        "revenue_cents": revenue,
        "noninterest_expense_cents": expense,
        "composite_score_bps": composite,
        "band": calc.performance_band(composite),
    }, versioned=False)

    branch["snapshot_count"] = branch["snapshot_count"] + 1
    svc.refresh_branch_score(branch)
    touch(branch)
    return object_response(public(rec), 201)


@bp.get("/distribution/branches/<branch_id>/performance-snapshots")
def list_branch_snapshots(branch_id):
    authorize(READ_SNAPSHOT)
    limit, offset = pagination()
    svc.path_lookup("branches", branch_id, "Branch")
    rows = calc.ordered_snapshots(branch_id)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


@bp.get("/distribution/performance-snapshots/<snapshot_id>")
def read_snapshot(snapshot_id):
    authorize(READ_SNAPSHOT)
    rec = svc.path_lookup("performance_snapshots", snapshot_id, "Performance snapshot")
    return object_response(public(rec))


@bp.get("/distribution/performance-snapshots")
def list_snapshots():
    authorize(READ_SNAPSHOT)
    limit, offset = pagination()
    branch_id = filter_value("branch_id")
    band = filter_value("band", SNAPSHOT_BANDS)
    rows = all_of("performance_snapshots")
    if branch_id is not None:
        rows = [r for r in rows if r["branch_id"] == branch_id]
    if band is not None:
        rows = [r for r in rows if r["band"] == band]
    rows = svc.oldest_first(rows)
    page, total = window(rows, limit, offset)
    return list_response([public(r) for r in page], limit, offset, total)


@bp.get("/distribution/branches/<branch_id>/performance-score")
def branch_performance_score(branch_id):
    user_id, role = authorize(("NetworkStrategist", "ConsolidationApprover",
                               "NetworkOpsAdmin", "BranchManager"))
    require_branch_ownership(user_id, role, branch_id)
    variant = filter_value("scoring_variant", SCORING_VARIANTS)
    branch = svc.path_lookup("branches", branch_id, "Branch")
    if branch["snapshot_count"] == 0:
        fail("ERR_NO_PERFORMANCE_HISTORY",
             "Branch '%s' has no performance history to score." % branch_id)
    if variant is None:
        variant = branch["scoring_variant"]
    score, band, contributing = calc.score_history(branch_id, variant)
    return object_response({
        "branch_id": branch_id,
        "scoring_variant": variant,
        "performance_score_bps": score,
        "performance_band": band,
        "contributing_snapshot_count": contributing,
    })
