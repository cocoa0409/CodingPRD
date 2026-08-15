"""External workshop requests: pre-approval, evidence, reimbursement."""
from datetime import timedelta
from flask import Blueprint, request

from auth import require_role, require_any_role
from db import store, new_resource, touch, now, fiscal_year
from envelope import ok, paginate, get_body, sort_by_created
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, \
    ERR_EMPLOYEE_NOT_ACTIVE, ERR_NOT_RESOURCE_OWNER, \
    ERR_BUILDING_SCOPE_VIOLATION, ERR_SEGREGATION_OF_DUTIES, \
    ERR_PREAPPROVAL_LEAD_TIME, ERR_APPROVAL_AFTER_START, \
    ERR_WORKSHOP_NOT_STARTED, ERR_REVISION_LIMIT_EXCEEDED, \
    ERR_BUDGET_NOT_OPEN, ERR_BUDGET_INSUFFICIENT
from routes.registrations import check_plan_alignment
from serializers import ser_workshop, budget_available
from services import find_budget, encumber, release_encumbrance, \
    complete_workshop, ANNUAL_CAP_CENTS
from validate import req_str, opt_str, req_int, opt_int, req_number, \
    opt_number, req_datetime, opt_datetime

bp = Blueprint("workshops", __name__)

LEAD = timedelta(days=14)


def get_workshop_or_404(wid):
    w = store.workshops.get(wid)
    if w is None:
        raise err(ERR_NOT_FOUND, "workshop request not found")
    return w


def _teacher_owns(ctx, workshop):
    return ctx.role != "Teacher" or ctx.user_id == workshop["teacher_id"]


@bp.post("/pd/workshop-requests")
def create_workshop():
    ctx = require_role("Teacher", "PDCoordinator")
    body = get_body()
    # shape (4)
    teacher_id = req_str(body, "teacher_id")
    title = req_str(body, "title")
    provider = req_str(body, "provider")
    starts = req_datetime(body, "starts_at")
    ends = req_datetime(body, "ends_at")
    est = req_int(body, "est_cost_cents", minimum=1)
    hours = req_number(body, "clock_hours_claimed", gt=0)
    building_id = opt_str(body, "building_id")
    plan_id = opt_str(body, "growth_plan_id")
    if not (ends > starts):
        raise err(ERR_INVALID_REQUEST, "ends_at must be after starts_at")
    # FK (5)
    emp = store.employees.get(teacher_id)
    if emp is None:
        raise err(ERR_NOT_FOUND, "teacher_id not found")
    if building_id is None:
        building_id = emp["primary_building_id"]
    elif building_id not in store.buildings:
        raise err(ERR_NOT_FOUND, "building_id not found")
    plan = None
    if plan_id is not None:
        plan = store.growth_plans.get(plan_id)
        if plan is None:
            raise err(ERR_NOT_FOUND, "growth_plan_id not found")
    # state (6)
    if emp["status"] != "ACTIVE":
        raise err(ERR_EMPLOYEE_NOT_ACTIVE, "employee is not ACTIVE")
    # ownership / alignment (8)
    if ctx.role == "Teacher" and ctx.user_id != teacher_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "teachers act only on their own")
    if plan is not None:
        check_plan_alignment(plan, teacher_id, starts, ends)
    w = new_resource()
    w.update({
        "teacher_id": teacher_id,
        "building_id": building_id,
        "title": title,
        "provider": provider,
        "starts_at": starts,
        "ends_at": ends,
        "est_cost_cents": est,
        "clock_hours_claimed": hours,
        "growth_plan_id": plan_id,
        "status": "DRAFT",
        "revision_count": 0,
        "reject_reason": None,
        "approved_by_user_id": None,
        "actual_hours": None,
        "receipt_cents": None,
        "reimbursed_cents": None,
    })
    store.workshops[w["id"]] = w
    return ok(ser_workshop(w), 201)


@bp.get("/pd/workshop-requests/<wid>")
def get_workshop(wid):
    require_any_role()
    return ok(ser_workshop(get_workshop_or_404(wid)), 200)


@bp.get("/pd/workshop-requests")
def list_workshops():
    require_any_role()
    items = store.workshops.values()
    for key in ("teacher_id", "building_id", "status", "growth_plan_id"):
        v = request.args.get(key)
        if v is not None:
            items = [w for w in items if w[key] == v]
    return paginate([ser_workshop(w) for w in sort_by_created(items)])


@bp.post("/pd/workshop-requests/<wid>/submit")
def submit_workshop(wid):
    ctx = require_role("Teacher", "PDCoordinator")
    get_body()
    w = get_workshop_or_404(wid)
    if w["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "only a DRAFT request can be submitted")
    if not _teacher_owns(ctx, w):
        raise err(ERR_NOT_RESOURCE_OWNER, "not your workshop request")
    if w["starts_at"] < now() + LEAD:
        raise err(ERR_PREAPPROVAL_LEAD_TIME,
                  "starts_at must be at least 14 days after now")
    w["status"] = "SUBMITTED"
    touch(w)
    return ok(ser_workshop(w), 200)


def _check_admin_scope(ctx, w):
    if ctx.employee["primary_building_id"] != w["building_id"]:
        raise err(ERR_BUILDING_SCOPE_VIOLATION,
                  "request is outside the admin's building")


@bp.post("/pd/workshop-requests/<wid>/approve")
def approve_workshop(wid):
    ctx = require_role("BuildingAdmin")
    get_body()
    w = get_workshop_or_404(wid)
    if w["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "only a SUBMITTED request can be approved")
    _check_admin_scope(ctx, w)
    if not (now() < w["starts_at"]):
        raise err(ERR_APPROVAL_AFTER_START,
                  "approval must precede the workshop start")
    budget = find_budget(w["building_id"], fiscal_year(w["starts_at"]))
    if budget is None or budget["status"] != "OPEN":
        raise err(ERR_BUDGET_NOT_OPEN, "no OPEN budget for building/year")
    if budget_available(budget) < w["est_cost_cents"]:
        raise err(ERR_BUDGET_INSUFFICIENT,
                  "available_cents below est_cost_cents")
    encumber(budget, w["est_cost_cents"])
    w["approved_by_user_id"] = ctx.user_id
    w["status"] = "APPROVED"
    touch(w)
    return ok(ser_workshop(w), 200)


@bp.post("/pd/workshop-requests/<wid>/reject")
def reject_workshop(wid):
    ctx = require_role("BuildingAdmin")
    w = get_workshop_or_404(wid)
    body = get_body()
    reason = req_str(body, "reason")
    if w["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "only a SUBMITTED request can be rejected")
    _check_admin_scope(ctx, w)
    w["status"] = "REJECTED"
    w["reject_reason"] = reason
    touch(w)
    return ok(ser_workshop(w), 200)


@bp.post("/pd/workshop-requests/<wid>/revise")
def revise_workshop(wid):
    ctx = require_role("Teacher", "PDCoordinator")
    w = get_workshop_or_404(wid)
    body = get_body()
    # shape (4): optional editable fields, type/range checked if present
    title = opt_str(body, "title")
    provider = opt_str(body, "provider")
    starts = opt_datetime(body, "starts_at")
    ends = opt_datetime(body, "ends_at")
    est = opt_int(body, "est_cost_cents", minimum=1)
    hours = opt_number(body, "clock_hours_claimed", gt=0)
    eff_starts = starts if starts is not None else w["starts_at"]
    eff_ends = ends if ends is not None else w["ends_at"]
    if not (eff_ends > eff_starts):
        raise err(ERR_INVALID_REQUEST, "ends_at must be after starts_at")
    # state (6)
    if w["status"] != "REJECTED":
        raise err(ERR_INVALID_STATE, "only a REJECTED request can be revised")
    # ownership (8)
    if not _teacher_owns(ctx, w):
        raise err(ERR_NOT_RESOURCE_OWNER, "not your workshop request")
    # domain (10)
    if w["revision_count"] >= 3:
        raise err(ERR_REVISION_LIMIT_EXCEEDED, "revision limit reached")
    if title is not None:
        w["title"] = title
    if provider is not None:
        w["provider"] = provider
    if starts is not None:
        w["starts_at"] = starts
    if ends is not None:
        w["ends_at"] = ends
    if est is not None:
        w["est_cost_cents"] = est
    if hours is not None:
        w["clock_hours_claimed"] = hours
    w["status"] = "DRAFT"
    w["revision_count"] += 1
    touch(w)
    return ok(ser_workshop(w), 200)


@bp.post("/pd/workshop-requests/<wid>/complete")
def complete_workshop_endpoint(wid):
    ctx = require_role("Teacher", "PDCoordinator")
    w = get_workshop_or_404(wid)
    body = get_body()
    actual = req_number(body, "actual_hours", gt=0)
    receipt = req_int(body, "receipt_cents", minimum=0)
    if w["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "only an APPROVED request can complete")
    if not _teacher_owns(ctx, w):
        raise err(ERR_NOT_RESOURCE_OWNER, "not your workshop request")
    if not (now() >= w["starts_at"]):
        raise err(ERR_WORKSHOP_NOT_STARTED, "workshop has not started")
    w["actual_hours"] = actual
    w["receipt_cents"] = receipt
    complete_workshop(w)
    return ok(ser_workshop(w), 200)


def _segregation_check(ctx, w):
    if ctx.user_id == w["approved_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  "approver cannot settle reimbursement")


@bp.post("/pd/workshop-requests/<wid>/reimburse")
def reimburse_workshop(wid):
    ctx = require_role("BusinessOfficer")
    get_body()
    w = get_workshop_or_404(wid)
    if w["status"] != "ATTENDED":
        raise err(ERR_INVALID_STATE, "only an ATTENDED request is reimbursable")
    _segregation_check(ctx, w)
    fy = fiscal_year(w["starts_at"])
    prior = 0
    for other in store.workshops.values():
        if (other["teacher_id"] == w["teacher_id"]
                and other["status"] == "REIMBURSED"
                and fiscal_year(other["starts_at"]) == fy
                and other["reimbursed_cents"] is not None):
            prior += other["reimbursed_cents"]
    remaining_cap = max(0, ANNUAL_CAP_CENTS - prior)
    amount = min(w["receipt_cents"], w["est_cost_cents"], remaining_cap)
    w["reimbursed_cents"] = amount
    w["status"] = "REIMBURSED"
    touch(w)
    budget = find_budget(w["building_id"], fy)
    if budget is not None:
        budget["encumbered_cents"] -= w["est_cost_cents"]
        budget["spent_cents"] += amount
        touch(budget)
    return ok(ser_workshop(w), 200)


@bp.post("/pd/workshop-requests/<wid>/deny-reimbursement")
def deny_workshop(wid):
    ctx = require_role("BusinessOfficer")
    w = get_workshop_or_404(wid)
    body = get_body()
    req_str(body, "reason")
    if w["status"] != "ATTENDED":
        raise err(ERR_INVALID_STATE, "only an ATTENDED request can be denied")
    _segregation_check(ctx, w)
    w["status"] = "REIMBURSEMENT_DENIED"
    touch(w)
    budget = find_budget(w["building_id"], fiscal_year(w["starts_at"]))
    if budget is not None:
        release_encumbrance(budget, w["est_cost_cents"])
    return ok(ser_workshop(w), 200)
