"""Assignment endpoints (PRD §3.4, §3.5)."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_ASSIGNMENT_INVALID_STATE, ERR_INSUFFICIENT_BUDGET, ERR_PLAN_NOT_ACTIVE,
    ERR_QUALIFICATION_NOT_CURRENT, ERR_SCHEDULE_OVERLAP, ERR_STALE_VERSION,
    ERR_STUDENT_NOT_ASSIGNABLE, ERR_WEEKLY_CAP, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import (
    as_date_str, as_days_of_week, as_int, as_str, bad_request, body_json, need,
    parse_date,
)

bp = Blueprint("assignments", __name__)

COORD = {"SpecialEdCoordinator"}
ANY = {"Any"}
MINUTE_MAX = 1439


def _auth(allowed):
    auth_context()
    require_role(request.headers.get("X-User-Role"), allowed)


def _not_current():
    raise ApiError(ERR_QUALIFICATION_NOT_CURRENT, 422,
                   "para does not hold the required qualification current")


@bp.post("/sped-staffing/assignments")
def create_assignment():
    _auth(COORD)
    body = body_json(request)
    # Body FK existence (priority 3) for present references.
    plan_id = need(body, "plan_id")
    plan = svc.get_plan(as_str(plan_id, "plan_id"))
    student_id = need(body, "student_id")
    student = svc.get_student(as_str(student_id, "student_id"))
    para_id = need(body, "para_id")
    para = svc.get_para(as_str(para_id, "para_id"))
    building_id = need(body, "building_id")
    building = svc.get_building(as_str(building_id, "building_id"))
    # Structural validation.
    start_date = as_date_str(need(body, "start_date"), "start_date")
    end_date = as_date_str(need(body, "end_date"), "end_date")
    days = as_days_of_week(need(body, "days_of_week"))
    daily_start = as_int(need(body, "daily_start_minute"), "daily_start_minute")
    daily_end = as_int(need(body, "daily_end_minute"), "daily_end_minute")
    if "expected_plan_version" not in body or body["expected_plan_version"] is None:
        bad_request("expected_plan_version is required")
    expected_version = as_int(body["expected_plan_version"], "expected_plan_version")
    # State (4a): plan must be ACTIVE.
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409,
                       "assignment proposal requires plan ACTIVE")
    # OCC (4c): expected plan version must match.
    if expected_version != plan["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_plan_version does not match the plan version")
    # Snapshots taken at creation (never track their sources again).
    service_level_snapshot = student["iep_service_level"]
    required_qual_snapshot = student["required_qualification"]
    base_wage_snapshot = para["base_hourly_wage_cents"]
    # Business safety (5): qualification currency at the current logical date.
    today = db.now().date()
    if not svc.qual_current(para, required_qual_snapshot, today):
        _not_current()
    # Business constraints (6a): schedule overlap vs the para's ACTIVE assignments.
    if svc.para_has_conflict(para, plan, days, daily_start, daily_end,
                             building["id"]):
        raise ApiError(ERR_SCHEDULE_OVERLAP, 409,
                       "schedule conflict with an existing ACTIVE assignment")
    # Business constraints (6d): weekly capacity.
    daily_minutes = daily_end - daily_start
    weekly_minutes = daily_minutes * len(days)
    if svc.weekly_minutes_of(para) + weekly_minutes > para["contracted_max_weekly_minutes"]:
        raise ApiError(ERR_WEEKLY_CAP, 422,
                       "weekly scheduled minutes would exceed the contracted cap")
    # Date coherence (7).
    if daily_start < 0 or daily_start > MINUTE_MAX:
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "daily_start_minute must be a minute-of-day 0..1439")
    if daily_end <= daily_start or daily_end > MINUTE_MAX + 1:
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "daily_end_minute must be strictly after daily_start_minute")
    if parse_date(end_date) < parse_date(start_date):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "end_date must not precede start_date")
    # Assemble and cost the candidate (pinned costing order).
    assignment = {
        "plan_id": plan["id"],
        "student_id": student["id"],
        "para_id": para["id"],
        "building_id": building["id"],
        "start_date": start_date,
        "end_date": end_date,
        "days_of_week": days,
        "daily_start_minute": daily_start,
        "daily_end_minute": daily_end,
        "service_level_snapshot": service_level_snapshot,
        "required_qualification_snapshot": required_qual_snapshot,
        "base_wage_snapshot_cents": base_wage_snapshot,
        "weekly_minutes": weekly_minutes,
        "daily_cost_cents": 0,
        "projected_weekly_cost_cents": 0,
        "end_reason": None,
        "status": "PROPOSED",
        "funding_status": "PROVISIONALLY_FUNDED",
        "_cost_locked": False,
        "_cost_surcharged": False,
    }
    svc.cost_assignment(assignment, para, plan)
    # Fiscal check (9): runs last.
    if (svc.committed_cost(plan) + assignment["projected_weekly_cost_cents"]
            > plan["total_budget_cents"] - plan["settled_cost_cents"]):
        raise ApiError(ERR_INSUFFICIENT_BUDGET, 402,
                       "committed cost plus candidate exceeds remaining budget")
    svc.stamp_new(assignment)
    db.STORE["assignments"][assignment["id"]] = assignment
    # Committed share absorbed; plan version increments by one.
    plan["version"] += 1
    plan["updated_at"] = assignment["created_at"]
    return success(svc.ser_assignment(assignment), "object", 201)


@bp.get("/sped-staffing/assignments")
def list_assignments():
    _auth(ANY)
    plan_id = request.args.get("plan_id")
    student_id = request.args.get("student_id")
    para_id = request.args.get("para_id")
    building_id = request.args.get("building_id")
    status = request.args.get("status")
    items = []
    for a in svc.sorted_records("assignments"):
        if plan_id is not None and a["plan_id"] != plan_id:
            continue
        if student_id is not None and a["student_id"] != student_id:
            continue
        if para_id is not None and a["para_id"] != para_id:
            continue
        if building_id is not None and a["building_id"] != building_id:
            continue
        if status is not None and a["status"] != status:
            continue
        items.append(svc.ser_assignment(a))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/sped-staffing/assignments/<assignmentId>")
def get_assignment(assignmentId):
    _auth(ANY)
    a = svc.get_assignment(assignmentId)
    return success(svc.ser_assignment(a), "object", 200)


@bp.post("/sped-staffing/assignments/<assignmentId>/verify-qualifications")
def verify_qualifications(assignmentId):
    _auth(COORD)
    a = svc.get_assignment(assignmentId)
    if a["status"] != "PROPOSED":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, 409,
                       "verify-qualifications requires assignment PROPOSED")
    para = db.STORE["paras"][a["para_id"]]
    if not svc.qual_current(para, a["required_qualification_snapshot"],
                            db.now().date()):
        _not_current()
    a["status"] = "QUALIFICATION_VERIFIED"
    svc.touch(a)
    return success(svc.ser_assignment(a), "object", 200)


@bp.post("/sped-staffing/assignments/<assignmentId>/activate")
def activate_assignment(assignmentId):
    _auth(COORD)
    a = svc.get_assignment(assignmentId)
    if a["status"] != "QUALIFICATION_VERIFIED":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, 409,
                       "activation requires assignment QUALIFICATION_VERIFIED")
    plan = db.STORE["plans"][a["plan_id"]]
    student = db.STORE["students"][a["student_id"]]
    para = db.STORE["paras"][a["para_id"]]
    if student["status"] != "ACTIVE_IEP":
        raise ApiError(ERR_STUDENT_NOT_ASSIGNABLE, 409,
                       "activation requires student ACTIVE_IEP")
    # Funding gate: committed already includes this assignment since proposal.
    funded_ok = (a["funding_status"] == "PROVISIONALLY_FUNDED"
                 and svc.committed_cost(plan)
                 <= plan["total_budget_cents"] - plan["settled_cost_cents"])
    if not funded_ok:
        a["funding_status"] = "UNFUNDED"
        svc.touch(a)
        raise ApiError(ERR_INSUFFICIENT_BUDGET, 402,
                       "funding gate failed at activation")
    # Success: lock cost, fund, add minutes, recompute benefit.
    a["status"] = "ACTIVE"
    a["funding_status"] = "FUNDED"
    a["_cost_locked"] = True
    svc.touch(a)
    svc.refresh_benefit_and_recost(para, plan)
    return success(svc.ser_assignment(a), "object", 200)


@bp.post("/sped-staffing/assignments/<assignmentId>/suspend")
def suspend_assignment(assignmentId):
    _auth(COORD)
    a = svc.get_assignment(assignmentId)
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, 409,
                       "suspend requires assignment ACTIVE")
    plan = db.STORE["plans"][a["plan_id"]]
    para = db.STORE["paras"][a["para_id"]]
    svc.suspend_assignment(a, para, plan)
    return success(svc.ser_assignment(a), "object", 200)


@bp.post("/sped-staffing/assignments/<assignmentId>/resume")
def resume_assignment(assignmentId):
    _auth(COORD)
    a = svc.get_assignment(assignmentId)
    if a["status"] != "SUSPENDED":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, 409,
                       "resume requires assignment SUSPENDED")
    plan = db.STORE["plans"][a["plan_id"]]
    para = db.STORE["paras"][a["para_id"]]
    # Re-run the four checks in §2.7 order.
    if not svc.qual_current(para, a["required_qualification_snapshot"],
                            db.now().date()):
        _not_current()
    if svc.para_has_conflict(para, plan, a["days_of_week"],
                             a["daily_start_minute"], a["daily_end_minute"],
                             a["building_id"], exclude_id=a["id"]):
        raise ApiError(ERR_SCHEDULE_OVERLAP, 409,
                       "schedule conflict with an existing ACTIVE assignment")
    if (svc.weekly_minutes_of(para) + a["weekly_minutes"]
            > para["contracted_max_weekly_minutes"]):
        raise ApiError(ERR_WEEKLY_CAP, 422,
                       "weekly scheduled minutes would exceed the contracted cap")
    if (svc.committed_cost(plan) + a["projected_weekly_cost_cents"]
            > plan["total_budget_cents"] - plan["settled_cost_cents"]):
        a["funding_status"] = "UNFUNDED"
        svc.touch(a)
        raise ApiError(ERR_INSUFFICIENT_BUDGET, 402,
                       "budget re-check failed at resumption")
    a["status"] = "ACTIVE"
    a["funding_status"] = "FUNDED"
    svc.touch(a)
    svc.refresh_benefit_and_recost(para, plan)
    return success(svc.ser_assignment(a), "object", 200)


@bp.post("/sped-staffing/assignments/<assignmentId>/end")
def end_assignment(assignmentId):
    _auth(COORD)
    a = svc.get_assignment(assignmentId)
    if a["status"] == "ENDED":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, 409,
                       "assignment is already ENDED")
    plan = db.STORE["plans"][a["plan_id"]]
    para = db.STORE["paras"][a["para_id"]]
    svc.end_assignment(a, para, plan, "COORDINATOR_ENDED")
    return success(svc.ser_assignment(a), "object", 200)
