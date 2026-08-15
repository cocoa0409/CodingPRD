"""CapitalPlan / CapitalProject routes: ranking, budget-gated approval,
cooling-period lock, and project side exits (PRD 3.10)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
import services
from envelope import success
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_DUPLICATE_PLAN_YEAR,
    ERR_BUDGET_EXCEEDED,
    ERR_PLAN_NOT_SETTLED,
    ERR_PLAN_LOCKED,
)
from helpers import (
    body, bad, is_int, req_str, req_decimal, paginate,
)
from middleware import require_roles
from serializers import ser_plan, ser_project

bp = Blueprint("capital", __name__)

CAPITAL_READ_ROLES = (
    "UtilityAdmin", "OperationsSupervisor", "CapitalProgramManager",
)

LOCK_SETTLE_DAYS = 7


def get_plan_or_404(pid):
    p = db.capital_plans.get(pid)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Capital plan not found")
    return p


def get_project_or_404(pid):
    p = db.capital_projects.get(pid)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Capital project not found")
    return p


# --------------------------------------------------------------------- plans


@bp.post("/capital-plans")
def create_plan():
    require_roles("CapitalProgramManager")
    b = body()
    # business constraint (priority 15): uniqueness
    year = b.get("plan_year")
    if year is not None and is_int(year):
        for p in db.capital_plans.values():
            if p["plan_year"] == year:
                raise ApiError(
                    ERR_DUPLICATE_PLAN_YEAR, 422,
                    "plan_year %s already exists" % year,
                )
    # shape (priority 30)
    if year is None or not is_int(year):
        bad("plan_year is required and must be an integer")
    if year < 2024 or year > 2100:
        bad("plan_year must be in [2024, 2100]")
    total = req_decimal(b, "budget_total_usd", 2)
    if total < 0:
        bad("budget_total_usd must be >= 0")
    plan = {
        "id": db.new_id(),
        "plan_year": year,
        "status": "DRAFT",
        "budget_total_usd": total,
        "budget_allocated_usd": Decimal("0.00"),
        "approved_at": None,
    }
    db.stamp(plan)
    db.capital_plans[plan["id"]] = plan
    return success(ser_plan(plan), 201)


@bp.get("/capital-plans")
def list_plans():
    require_roles(*CAPITAL_READ_ROLES)
    items = list(db.capital_plans.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    year = request.args.get("plan_year")
    if year is not None:
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            bad("plan_year must be an integer")
        items = [p for p in items if p["plan_year"] == year_int]
    page, meta = paginate(items)
    return success([ser_plan(p) for p in page], 200, meta)


@bp.get("/capital-plans/<pid>")
def get_plan(pid):
    require_roles(*CAPITAL_READ_ROLES)
    return success(ser_plan(get_plan_or_404(pid)))


@bp.post("/capital-plans/<pid>/rank")
def rank_plan(pid):
    require_roles("CapitalProgramManager")
    plan = get_plan_or_404(pid)
    if plan["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT plan can be ranked")
    proposed = [
        p for p in db.capital_projects.values()
        if p["plan_id"] == pid and p["status"] == "PROPOSED"
    ]
    if len(proposed) < 1:
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Ranking requires at least one PROPOSED project",
        )
    # Assign priority ranks and cascade PROPOSED -> RANKED (touches each).
    services.rank_projects(plan)
    plan["status"] = "RANKED"
    plan["budget_allocated_usd"] = services.plan_allocated(pid)
    db.touch(plan)
    return success(ser_plan(plan))


@bp.post("/capital-plans/<pid>/approve")
def approve_plan(pid):
    require_roles("UtilityAdmin")
    plan = get_plan_or_404(pid)
    if plan["status"] != "RANKED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a RANKED plan can be approved")
    # OCC guard (PRD 2.6)
    b = body()
    expected = b.get("expected_plan_version")
    if expected is None or not is_int(expected):
        bad("expected_plan_version is required and must be an integer")
    if expected != plan["version"]:
        raise ApiError(
            ERR_STALE_VERSION, 412,
            "expected_plan_version does not match the plan's current version",
        )
    # referential (priority 25): allocated may not exceed the authorized total
    plan["budget_allocated_usd"] = services.plan_allocated(pid)
    if plan["budget_allocated_usd"] > plan["budget_total_usd"]:
        raise ApiError(
            ERR_BUDGET_EXCEEDED, 422,
            "budget_allocated_usd exceeds budget_total_usd",
        )
    # Budget-prefix walk: approve the longest prefix of RANKED projects whose
    # cumulative estimated cost stays within budget; defer the rest.
    ranked = [
        p for p in db.capital_projects.values()
        if p["plan_id"] == pid and p["status"] == "RANKED"
    ]
    ranked.sort(key=lambda p: (p["priority_rank"], p["_seq"]))
    cumulative = Decimal("0.00")
    for p in ranked:
        if cumulative + p["estimated_cost_usd"] <= plan["budget_total_usd"]:
            cumulative += p["estimated_cost_usd"]
            p["status"] = "APPROVED"
        else:
            p["status"] = "DEFERRED"
        db.touch(p)
    plan["approved_at"] = db.now()
    plan["status"] = "APPROVED"
    plan["budget_allocated_usd"] = services.plan_allocated(pid)
    db.touch(plan)
    return success(ser_plan(plan))


@bp.post("/capital-plans/<pid>/lock")
def lock_plan(pid):
    require_roles("UtilityAdmin")
    plan = get_plan_or_404(pid)
    if plan["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an APPROVED plan can be locked")
    # fiscal (priority 26): seven-day cooling period after approval
    if db.now() < plan["approved_at"] + timedelta(days=LOCK_SETTLE_DAYS):
        raise ApiError(
            ERR_PLAN_NOT_SETTLED, 422,
            "Plan cannot be locked until 7 days after approved_at",
        )
    plan["status"] = "LOCKED"
    db.touch(plan)
    return success(ser_plan(plan))


@bp.post("/capital-plans/<pid>/unrank")
def unrank_plan(pid):
    require_roles("CapitalProgramManager")
    plan = get_plan_or_404(pid)
    if plan["status"] != "RANKED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a RANKED plan can be unranked")
    for p in db.capital_projects.values():
        if p["plan_id"] == pid and p["status"] == "RANKED":
            p["status"] = "PROPOSED"
            p["priority_rank"] = None
            db.touch(p)
    plan["status"] = "DRAFT"
    plan["budget_allocated_usd"] = services.plan_allocated(pid)
    db.touch(plan)
    return success(ser_plan(plan))


# --------------------------------------------------------------------- projects


@bp.post("/capital-projects")
def create_project():
    require_roles("CapitalProgramManager")
    b = body()
    # body FK existence (priority 5)
    plan_id = b.get("plan_id")
    if plan_id is None:
        bad("plan_id is required")
    if not isinstance(plan_id, str):
        bad("plan_id must be a string")
    plan = db.capital_plans.get(plan_id)
    if plan is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "plan_id does not resolve")
    station_id = b.get("station_id")
    if station_id is None:
        bad("station_id is required")
    if not isinstance(station_id, str):
        bad("station_id must be a string")
    station = db.stations.get(station_id)
    if station is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "station_id does not resolve")
    # shape (priority 30)
    name = req_str(b, "project_name")
    cost = req_decimal(b, "estimated_cost_usd", 2)
    if cost <= 0:
        bad("estimated_cost_usd must be > 0")
    cof = b.get("consequence_of_failure")
    if not is_int(cof) or cof < 1 or cof > 10:
        bad("consequence_of_failure must be an integer in [1, 10]")
    lof = b.get("likelihood_of_failure")
    if not is_int(lof) or lof < 1 or lof > 10:
        bad("likelihood_of_failure must be an integer in [1, 10]")
    p = {
        "id": db.new_id(),
        "plan_id": plan_id,
        "station_id": station_id,
        "project_name": name,
        "estimated_cost_usd": cost,
        "risk_score": None,
        "priority_rank": None,
        "status": "PROPOSED",
        "consequence_of_failure": cof,
        "likelihood_of_failure": lof,
    }
    p["risk_score"] = services.compute_risk_score(p, station)
    db.stamp(p)
    db.capital_projects[p["id"]] = p
    services.sync_plan_budget(plan)
    return success(ser_project(p), 201)


@bp.get("/capital-plans/<pid>/capital-projects")
def list_plan_projects(pid):
    require_roles(*CAPITAL_READ_ROLES)
    get_plan_or_404(pid)
    items = [p for p in db.capital_projects.values() if p["plan_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items)
    return success([ser_project(p) for p in page], 200, meta)


@bp.get("/capital-projects")
def list_projects():
    require_roles(*CAPITAL_READ_ROLES)
    items = list(db.capital_projects.values())
    for field in ("plan_id", "station_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [p for p in items if p[field] == v]
    page, meta = paginate(items)
    return success([ser_project(p) for p in page], 200, meta)


@bp.get("/capital-projects/<pid>")
def get_project(pid):
    require_roles(*CAPITAL_READ_ROLES)
    return success(ser_project(get_project_or_404(pid)))


def _reject_or_cancel(pid, target):
    require_roles("CapitalProgramManager")
    p = get_project_or_404(pid)
    plan = db.capital_plans[p["plan_id"]]
    if p["status"] != "PROPOSED":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a PROPOSED project can be %s" % target,
        )
    # fiscal (priority 27): sealed once the parent plan is LOCKED
    if plan["status"] == "LOCKED":
        raise ApiError(
            ERR_PLAN_LOCKED, 409,
            "Projects cannot be rejected or cancelled while the plan is LOCKED",
        )
    p["status"] = target
    db.touch(p)
    services.sync_plan_budget(plan)
    return success(ser_project(p))


@bp.post("/capital-projects/<pid>/reject")
def reject_project(pid):
    return _reject_or_cancel(pid, "REJECTED")


@bp.post("/capital-projects/<pid>/cancel")
def cancel_project(pid):
    return _reject_or_cancel(pid, "CANCELLED")


@bp.post("/capital-projects/<pid>/resubmit")
def resubmit_project(pid):
    require_roles("CapitalProgramManager")
    p = get_project_or_404(pid)
    plan = db.capital_plans[p["plan_id"]]
    if p["status"] != "DEFERRED":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Only a DEFERRED project can be resubmitted"
        )
    if plan["status"] != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Resubmission requires the parent plan to be back in DRAFT",
        )
    p["status"] = "PROPOSED"
    p["priority_rank"] = None
    db.touch(p)
    services.sync_plan_budget(plan)
    return success(ser_project(p))
