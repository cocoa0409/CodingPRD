"""LaborEntry endpoints: prevailing-wage costing frozen at creation, payroll workflow."""
from flask import Blueprint, g, request

import db
from calc import labor_cost
from errors import (ApiError, ERR_INVALID_STATE, ERR_SAFETY_HOLD,
                    ERR_SEGREGATION_OF_DUTIES)
from helpers import labor_or_404, project_or_404, sorted_items, touch
from middleware import ROLES, require_roles
from response import success, success_list
from serialize import labor_json
from util import new_id, now_iso
from validators import get_body, pagination, req_date, req_enum, req_num, req_str

bp = Blueprint("labor_entries", __name__)

CLASSIFICATIONS = ("MW_JOURNEYMAN", "MW_APPRENTICE", "MW_FOREMAN", "OPERATOR")


@bp.post("/v1/labor-entries")
@require_roles("SiteSupervisor")
def create_labor_entry():
    body = get_body()
    pid = body.get("project_id")
    project = project_or_404(pid) if isinstance(pid, str) else None
    # schema (priority 7)
    req_str(body, "project_id")
    worker_ref = req_str(body, "worker_ref")
    classification = req_enum(body, "classification", CLASSIFICATIONS)
    work_date = req_date(body, "work_date")
    # PRD section 3.8: hours_worked is "greater than zero and at most
    # twenty-four" — a per-entry bound, unconditional on ot_basis.
    hours_raw, hours_d = req_num(body, "hours_worked", gt=0, le=24)
    shift = req_enum(body, "shift", ("DAY", "NIGHT"))
    # safety interlock (priority 8)
    if project["hold_status"] != "CLEAR":
        raise ApiError(ERR_SAFETY_HOLD, 409, "project is under SAFETY_HOLD")
    cost = labor_cost(project, worker_ref, classification, work_date, hours_d, shift)
    ts = now_iso()
    e = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "project_id": project["id"],
        "worker_ref": worker_ref,
        "classification": classification,
        "work_date": work_date.isoformat(),
        "hours_worked": hours_raw,
        "shift": shift,
        "regular_hours": cost["regular_hours"],
        "overtime_hours": cost["overtime_hours"],
        "base_rate_cents": cost["base_rate_cents"],
        "total_cost_cents": cost["total_cost_cents"],
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "rejection_reason": None,
        "_work_date": work_date,
        "_seq": db.next_seq(),
    }
    db.labor_entries[e["id"]] = e
    return success(labor_json(e), 201)


@bp.get("/v1/projects/<pid>/labor-entries")
@require_roles(*ROLES)
def list_labor_entries(pid):
    project_or_404(pid)
    limit, offset = pagination()
    status = request.args.get("status")
    worker = request.args.get("worker_ref")
    items = [e for e in db.labor_entries.values() if e["project_id"] == pid]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if worker is not None:
        items = [e for e in items if e["worker_ref"] == worker]
    items = sorted_items(items)
    total = len(items)
    return success_list([labor_json(e) for e in items[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/v1/labor-entries/<eid>/submit")
@require_roles("SiteSupervisor")
def submit_labor_entry(eid):
    e = labor_or_404(eid)
    # state (priority 5): DRAFT or REJECTED (resubmission loop)
    if e["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a DRAFT or REJECTED labor entry can be submitted")
    # priority 8
    project = db.projects[e["project_id"]]
    if project["hold_status"] != "CLEAR":
        raise ApiError(ERR_SAFETY_HOLD, 409, "project is under SAFETY_HOLD")
    e["status"] = "SUBMITTED"
    e["submitted_by_user_id"] = g.user_id
    e["rejection_reason"] = None
    touch(e)
    return success(labor_json(e))


@bp.post("/v1/labor-entries/<eid>/approve")
@require_roles("PayrollClerk")
def approve_labor_entry(eid):
    e = labor_or_404(eid)
    if e["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SUBMITTED labor entry can be approved")
    # segregation of duties (priority 6): approver != submitter
    if g.user_id == e["submitted_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "approver must differ from the submitting supervisor")
    e["status"] = "APPROVED"
    e["approved_by_user_id"] = g.user_id
    touch(e)
    # rollup re-evaluation mutates the project
    touch(db.projects[e["project_id"]])
    return success(labor_json(e))


@bp.post("/v1/labor-entries/<eid>/reject")
@require_roles("PayrollClerk")
def reject_labor_entry(eid):
    e = labor_or_404(eid)
    # state (priority 5): SUBMITTED, or APPROVED-not-yet-invoiced reversal
    if e["status"] not in ("SUBMITTED", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SUBMITTED or APPROVED labor entry can be rejected")
    body = get_body()
    reason = req_str(body, "reason")
    was_approved = e["status"] == "APPROVED"
    e["status"] = "REJECTED"
    e["rejection_reason"] = reason
    touch(e)
    if was_approved:
        # compensation: approved_labor_cents rollup drops the entry; project mutates
        touch(db.projects[e["project_id"]])
    return success(labor_json(e))
