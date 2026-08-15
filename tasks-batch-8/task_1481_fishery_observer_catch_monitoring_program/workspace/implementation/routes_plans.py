"""Coverage plans, selection runs, and selection notices (PRD 3.2, 3.3)."""

import math

from flask import Blueprint

import logic
import store
from core import (
    ALL_ROLES, ApiError, body, err_forbidden, err_invalid, err_state,
    get_or_404, is_int, list_response, ok, parse_dt, req_dt, req_int,
    require_roles,
)

bp = Blueprint("plans", __name__, url_prefix="/observer-program")


# ---------------------------------------------------------------------------
# CoveragePlan
# ---------------------------------------------------------------------------


@bp.post("/coverage-plans")
def create_plan():
    require_roles("ProgramCoordinator")
    b = body()
    # Body FK existence (priority 3).
    fishery_id = b.get("fishery_id")
    if isinstance(fishery_id, str):
        get_or_404("fisheries", fishery_id, "Fishery")
    # Schema (priority 4).
    fishery_id = b.get("fishery_id")
    if not isinstance(fishery_id, str) or not fishery_id:
        raise err_invalid("Field 'fishery_id' is required")
    period_start = req_dt(b, "period_start")
    period_end = req_dt(b, "period_end")
    fleet_days = req_int(b, "projected_fleet_effort_days")
    em_days = req_int(b, "projected_em_effort_days")
    if fleet_days <= 0:
        raise err_invalid("projected_fleet_effort_days must be > 0")
    if em_days < 0:
        raise err_invalid("projected_em_effort_days must be >= 0")
    # Temporal (priority 8).
    if parse_dt(period_end) <= parse_dt(period_start):
        raise ApiError("ERR_DATE_RANGE_INVALID", 422,
                       "period_end must fall after period_start")
    plan = store.new_entity({
        "fishery_id": fishery_id,
        "period_start": period_start,
        "period_end": period_end,
        "projected_fleet_effort_days": fleet_days,
        "projected_em_effort_days": em_days,
        "required_observer_sea_days": None,
        "actual_fleet_effort_days": None,
        "final_required_observer_sea_days": None,
        "actual_observer_sea_days": 0,
        "actual_em_sea_days": 0,
        "coverage_attainment_pct": None,
        "status": "DRAFT",
    })
    store.db["coverage_plans"][plan["id"]] = plan
    return ok(plan, status=201)


@bp.get("/coverage-plans")
def list_plans():
    require_roles(*ALL_ROLES)
    return list_response("coverage_plans", {"fishery_id": "fishery_id", "status": "status"})


@bp.get("/coverage-plans/<pid>")
def get_plan(pid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("coverage_plans", pid, "CoveragePlan"))


@bp.post("/coverage-plans/<pid>/publish")
def publish_plan(pid):
    require_roles("ProgramCoordinator")
    plan = get_or_404("coverage_plans", pid, "CoveragePlan")
    if plan["status"] != "DRAFT":
        raise err_state("Only a DRAFT coverage plan can be published")
    fishery = store.db["fisheries"].get(plan["fishery_id"])
    if fishery is None or fishery["status"] != "ACTIVE":
        raise ApiError("ERR_FISHERY_NOT_ACTIVE", 409,
                       "The plan's fishery is not ACTIVE")
    # PROVISIONAL variant; the fishery's CURRENT target is read live.
    plan["required_observer_sea_days"] = logic.coverage_requirement(
        plan["projected_fleet_effort_days"], plan["projected_em_effort_days"],
        fishery["coverage_target_pct"],
    )
    plan["status"] = "PUBLISHED"
    store.touch(plan)
    return ok(plan)


@bp.post("/coverage-plans/<pid>/close")
def close_plan(pid):
    require_roles("ProgramCoordinator")
    plan = get_or_404("coverage_plans", pid, "CoveragePlan")
    b = body()
    actual_fleet = req_int(b, "actual_fleet_effort_days")
    if actual_fleet < 0:
        raise err_invalid("actual_fleet_effort_days must be >= 0")
    if plan["status"] != "SELECTION_COMPLETED":
        raise err_state("Only a SELECTION_COMPLETED coverage plan can be closed")
    open_deps = any(
        d["coverage_plan_id"] == plan["id"] and d["status"] in logic.OPEN_DEPLOYMENT_STATUSES
        for d in store.db["deployments"].values()
    )
    if open_deps:
        raise ApiError("ERR_PLAN_HAS_OPEN_DEPLOYMENTS", 409,
                       "The plan still has open deployments")
    # FINAL variant: actuals substitute for projections; fishery target live.
    fishery = store.db["fisheries"].get(plan["fishery_id"])
    target = fishery["coverage_target_pct"] if fishery is not None else 0
    final_required = logic.coverage_requirement(
        actual_fleet, plan["actual_em_sea_days"], target,
    )
    plan["actual_fleet_effort_days"] = actual_fleet
    plan["final_required_observer_sea_days"] = final_required
    if final_required == 0:
        from decimal import Decimal
        plan["coverage_attainment_pct"] = Decimal("0")
    else:
        from core import round4, dec
        plan["coverage_attainment_pct"] = round4(
            dec(plan["actual_observer_sea_days"]) / dec(final_required)
        )
    # Notice cascade: ISSUED -> EXPIRED; ACCEPTED with remaining > 0 ->
    # DEFAULTED (+2 penalty points); ACCEPTED with remaining == 0 -> FULFILLED.
    notices = [
        n for n in store.db["selection_notices"].values()
        if n["coverage_plan_id"] == plan["id"]
    ]
    notices.sort(key=lambda n: (n["created_at"], n["_seq"]))
    for notice in notices:
        if notice["status"] == "ISSUED":
            notice["status"] = "EXPIRED"
            store.touch(notice)
        elif notice["status"] == "ACCEPTED":
            if notice["remaining_sea_days"] == 0:
                notice["status"] = "FULFILLED"
            else:
                notice["status"] = "DEFAULTED"
                vessel = store.db["vessels"].get(notice["vessel_id"])
                if vessel is not None:
                    vessel["selection_penalty_points"] += 2
                    store.touch(vessel)
            store.touch(notice)
    plan["status"] = "CLOSED"
    store.touch(plan)
    return ok(plan)


# ---------------------------------------------------------------------------
# SelectionRun
# ---------------------------------------------------------------------------


@bp.post("/coverage-plans/<pid>/selection-runs")
def create_selection_run(pid):
    require_roles("ProgramCoordinator")
    plan = get_or_404("coverage_plans", pid, "CoveragePlan")
    b = body()
    deadline = req_dt(b, "notice_response_deadline")
    expected = b.get("expected_coverage_plan_version")
    if expected is None or not is_int(expected):
        raise err_invalid("Field 'expected_coverage_plan_version' is required and must be an integer")
    # OCC (priority 5) precedes state checks (priority 6).
    if expected != plan["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_coverage_plan_version does not match the plan's current version")
    if plan["status"] == "DRAFT":
        raise ApiError("ERR_PLAN_NOT_PUBLISHED", 409,
                       "Selection requires a PUBLISHED plan")
    if plan["status"] not in ("PUBLISHED", "SELECTION_COMPLETED"):
        raise err_state("Selection runs are not permitted in status " + plan["status"])
    fishery = store.db["fisheries"].get(plan["fishery_id"])
    if fishery is None or fishery["status"] != "ACTIVE":
        raise ApiError("ERR_FISHERY_NOT_ACTIVE", 409,
                       "The plan's fishery is not ACTIVE")

    required = plan["required_observer_sea_days"]
    pool = logic.eligible_vessels(plan)
    scored = [(v, logic.vessel_score(v, fishery, plan)) for v in pool]
    ranked = logic.rank_vessels(scored)
    vessels_to_select = math.ceil(required / logic.NOTICE_ALLOCATION_DAYS)
    selected = ranked[:max(0, min(vessels_to_select, len(ranked)))]

    run_index = sum(
        1 for r in store.db["selection_runs"].values()
        if r["coverage_plan_id"] == plan["id"]
    ) + 1
    run = store.new_entity({
        "coverage_plan_id": plan["id"],
        "run_index": run_index,
        "notice_response_deadline": deadline,
        "vessels_evaluated": len(pool),
        "vessels_selected": len(selected),
        "selection_deficit_sea_days": max(
            0, required - logic.NOTICE_ALLOCATION_DAYS * len(selected)),
    })
    store.db["selection_runs"][run["id"]] = run

    for rank, (vessel, score) in enumerate(selected, start=1):
        notice = store.new_entity({
            "selection_run_id": run["id"],
            "coverage_plan_id": plan["id"],
            "vessel_id": vessel["id"],
            "allocated_sea_days": logic.NOTICE_ALLOCATION_DAYS,
            "reserved_sea_days": 0,
            "consumed_sea_days": 0,
            "remaining_sea_days": logic.NOTICE_ALLOCATION_DAYS,
            "selection_score": score,
            "rank": rank,
            "response_deadline": deadline,
            "status": "ISSUED",
        })
        store.db["selection_notices"][notice["id"]] = notice

    plan["status"] = "SELECTION_COMPLETED"
    store.touch(plan)
    return ok(run, status=201)


@bp.get("/coverage-plans/<pid>/selection-runs")
def list_selection_runs(pid):
    require_roles(*ALL_ROLES)
    get_or_404("coverage_plans", pid, "CoveragePlan")
    from core import parse_pagination, ok_list
    limit, offset = parse_pagination()
    items = [
        r for r in store.db["selection_runs"].values()
        if r["coverage_plan_id"] == pid
    ]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list(page, {
        "limit": limit, "offset": offset, "total_count": total,
        "has_more": (offset + len(page)) < total,
    })


@bp.get("/selection-runs/<rid>")
def get_selection_run(rid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("selection_runs", rid, "SelectionRun"))


# ---------------------------------------------------------------------------
# SelectionNotice
# ---------------------------------------------------------------------------


@bp.get("/selection-notices")
def list_notices():
    require_roles(*ALL_ROLES)
    return list_response("selection_notices", {
        "selection_run_id": "selection_run_id",
        "coverage_plan_id": "coverage_plan_id",
        "vessel_id": "vessel_id",
        "status": "status",
    })


@bp.get("/selection-notices/<nid>")
def get_notice(nid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("selection_notices", nid, "SelectionNotice"))


def _notice_operator_check(a, notice):
    vessel = store.db["vessels"].get(notice["vessel_id"])
    if vessel is None or vessel["operator_id"] != a["id"]:
        raise err_forbidden("The acting operator does not own the notice's vessel")
    return vessel


@bp.post("/selection-notices/<nid>/accept")
def accept_notice(nid):
    a = require_roles("VesselOperator")
    notice = get_or_404("selection_notices", nid, "SelectionNotice")
    _notice_operator_check(a, notice)
    if notice["status"] != "ISSUED":
        raise err_state("Only an ISSUED notice can be accepted")
    if store.clock_now() > parse_dt(notice["response_deadline"]):
        raise ApiError("ERR_NOTICE_EXPIRED", 409,
                       "The notice response deadline has passed")
    notice["status"] = "ACCEPTED"
    store.touch(notice)
    return ok(notice)


@bp.post("/selection-notices/<nid>/decline")
def decline_notice(nid):
    a = require_roles("VesselOperator")
    notice = get_or_404("selection_notices", nid, "SelectionNotice")
    _notice_operator_check(a, notice)
    if notice["status"] != "ISSUED":
        raise err_state("Only an ISSUED notice can be declined")
    notice["status"] = "DECLINED"
    store.touch(notice)
    return ok(notice)
