"""StaffingPlan endpoints (PRD §3.1, §3.9)."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_PLAN_HAS_NO_BUILDINGS, ERR_PLAN_NOT_ACTIVE, ERR_PLAN_NOT_DRAFT,
    ERR_PLAN_NOT_RECONCILING, ERR_UNRECONCILED_COVERAGE_PLANS,
    ERR_UNRESOLVED_TIMESHEETS, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import as_int, as_num, as_str, bad_request, body_json, need, opt

bp = Blueprint("plans", __name__)

ADMIN = {"DistrictStaffingAdmin"}
ANY = {"Any"}


def _auth(allowed):
    auth_context()
    require_role(request.headers.get("X-User-Role"), allowed)


@bp.post("/sped-staffing/plans")
def create_plan():
    _auth(ADMIN)
    body = body_json(request)
    plan_name = as_str(need(body, "plan_name"), "plan_name")
    school_year = as_str(need(body, "school_year"), "school_year")
    total_budget = as_int(need(body, "total_budget_cents"), "total_budget_cents")
    if total_budget <= 0:
        bad_request("total_budget_cents must be > 0")
    threshold = as_int(opt(body, "benefit_threshold_minutes", 1800),
                       "benefit_threshold_minutes")
    surcharge = as_num(opt(body, "benefit_surcharge_pct", 0.20),
                       "benefit_surcharge_pct")
    buffer_minutes = as_int(opt(body, "travel_buffer_minutes", 30),
                            "travel_buffer_minutes")
    plan = {
        "plan_name": plan_name,
        "school_year": school_year,
        "total_budget_cents": total_budget,
        "benefit_threshold_minutes": threshold,
        "benefit_surcharge_pct": surcharge,
        "travel_buffer_minutes": buffer_minutes,
        "settled_cost_cents": 0,
        "status": "DRAFT",
    }
    svc.stamp_new(plan)
    db.STORE["plans"][plan["id"]] = plan
    return success(svc.ser_plan(plan), "object", 201)


@bp.get("/sped-staffing/plans")
def list_plans():
    _auth(ANY)
    items = [svc.ser_plan(p) for p in svc.sorted_records("plans")]
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/sped-staffing/plans/<planId>")
def get_plan(planId):
    _auth(ANY)
    plan = svc.get_plan(planId)
    return success(svc.ser_plan(plan), "object", 200)


@bp.post("/sped-staffing/plans/<planId>/activate")
def activate_plan(planId):
    _auth(ADMIN)
    plan = svc.get_plan(planId)
    if plan["status"] != "DRAFT":
        raise ApiError(ERR_PLAN_NOT_DRAFT, 409,
                       "plan activation requires DRAFT state")
    has_building = any(b["plan_id"] == plan["id"]
                       for b in db.STORE["buildings"].values())
    if not has_building:
        raise ApiError(ERR_PLAN_HAS_NO_BUILDINGS, 409,
                       "plan activation requires at least one building")
    plan["status"] = "ACTIVE"
    svc.touch(plan)
    return success(svc.ser_plan(plan), "object", 200)


@bp.post("/sped-staffing/plans/<planId>/begin-reconciliation")
def begin_reconciliation(planId):
    _auth(ADMIN)
    plan = svc.get_plan(planId)
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409,
                       "begin-reconciliation requires plan ACTIVE")
    plan["status"] = "RECONCILING"
    svc.touch(plan)
    return success(svc.ser_plan(plan), "object", 200)


@bp.post("/sped-staffing/plans/<planId>/reopen")
def reopen_plan(planId):
    _auth(ADMIN)
    plan = svc.get_plan(planId)
    if plan["status"] != "RECONCILING":
        raise ApiError(ERR_PLAN_NOT_RECONCILING, 409,
                       "reopen requires plan RECONCILING")
    plan["status"] = "ACTIVE"
    svc.touch(plan)
    return success(svc.ser_plan(plan), "object", 200)


@bp.post("/sped-staffing/plans/<planId>/close")
def close_plan(planId):
    _auth(ADMIN)
    plan = svc.get_plan(planId)
    if plan["status"] != "RECONCILING":
        raise ApiError(ERR_PLAN_NOT_RECONCILING, 409,
                       "close requires plan RECONCILING")
    for t in db.STORE["timesheets"].values():
        if t["plan_id"] == plan["id"] and t["status"] == "SUBMITTED":
            raise ApiError(ERR_UNRESOLVED_TIMESHEETS, 409,
                           "plan close blocked by SUBMITTED timesheets")
    for c in db.STORE["coverage_plans"].values():
        if c["plan_id"] == plan["id"] and c["status"] in (
                "DRAFT", "PUBLISHED", "LOCKED"):
            raise ApiError(ERR_UNRECONCILED_COVERAGE_PLANS, 409,
                           "plan close blocked by unreconciled coverage plans")
    svc.close_plan(plan)
    return success(svc.ser_plan(plan), "object", 200)
