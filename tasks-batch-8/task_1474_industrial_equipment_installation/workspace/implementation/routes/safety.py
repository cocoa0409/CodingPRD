"""SafetyPlan endpoints, including the suspend/resume safety-hold cascade."""
from flask import Blueprint

import db
from errors import (ApiError, ERR_INVALID_STATE, ERR_LOCKOUTS_OUTSTANDING,
                    ERR_SAFETY_PLAN_EXISTS)
from helpers import project_or_404, safety_plan_or_404, sorted_items, touch
from middleware import ROLES, require_roles
from response import success, success_list
from serialize import safety_plan_json
from util import new_id, now_iso
from validators import get_body, pagination, req_str

bp = Blueprint("safety_plans", __name__)


@bp.post("/v1/safety-plans")
@require_roles("SafetyOfficer")
def create_safety_plan():
    body = get_body()
    pid = body.get("project_id")
    if isinstance(pid, str):
        project_or_404(pid)
    pid = req_str(body, "project_id")
    plan_document_ref = req_str(body, "plan_document_ref")
    loto_procedure_ref = req_str(body, "loto_procedure_ref")
    # singleton (priority 16): at most one SafetyPlan per project, any status
    if any(sp["project_id"] == pid for sp in db.safety_plans.values()):
        raise ApiError(ERR_SAFETY_PLAN_EXISTS, 409,
                       "a safety plan already exists for the project")
    ts = now_iso()
    sp = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "project_id": pid,
        "plan_document_ref": plan_document_ref,
        "loto_procedure_ref": loto_procedure_ref,
        "status": "DRAFT",
        "_seq": db.next_seq(),
    }
    db.safety_plans[sp["id"]] = sp
    return success(safety_plan_json(sp), 201)


@bp.get("/v1/projects/<pid>/safety-plans")
@require_roles(*ROLES)
def list_safety_plans(pid):
    project_or_404(pid)
    limit, offset = pagination()
    items = sorted_items(sp for sp in db.safety_plans.values() if sp["project_id"] == pid)
    total = len(items)
    return success_list([safety_plan_json(sp) for sp in items[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/v1/safety-plans/<sid>/activate")
@require_roles("SafetyOfficer")
def activate_plan(sid):
    sp = safety_plan_or_404(sid)
    if sp["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "only a DRAFT safety plan can be activated")
    sp["status"] = "ACTIVE"
    touch(sp)
    return success(safety_plan_json(sp))


@bp.post("/v1/safety-plans/<sid>/suspend")
@require_roles("SafetyOfficer")
def suspend_plan(sid):
    sp = safety_plan_or_404(sid)
    if sp["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "only an ACTIVE safety plan can be suspended")
    sp["status"] = "SUSPENDED"
    touch(sp)
    # Cascade hop 1: project hold flips to SAFETY_HOLD
    project = db.projects[sp["project_id"]]
    project["hold_status"] = "SAFETY_HOLD"
    # Cascade hop 2: every SUBMITTED labor entry of the project -> REJECTED
    for e in db.labor_entries.values():
        if e["project_id"] == project["id"] and e["status"] == "SUBMITTED":
            e["status"] = "REJECTED"
            e["rejection_reason"] = "SAFETY_HOLD"
            touch(e)
    # Cascade hop 3: project derived fields re-evaluated, version increments once
    touch(project)
    return success(safety_plan_json(sp))


@bp.post("/v1/safety-plans/<sid>/resume")
@require_roles("SafetyOfficer")
def resume_plan(sid):
    sp = safety_plan_or_404(sid)
    if sp["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "only a SUSPENDED safety plan can be resumed")
    sp["status"] = "ACTIVE"
    touch(sp)
    # Compensating transition: clears the hold, leaves cascade-rejected labor REJECTED
    project = db.projects[sp["project_id"]]
    project["hold_status"] = "CLEAR"
    touch(project)
    return success(safety_plan_json(sp))


@bp.post("/v1/safety-plans/<sid>/close")
@require_roles("SafetyOfficer")
def close_plan(sid):
    sp = safety_plan_or_404(sid)
    if sp["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an ACTIVE or SUSPENDED safety plan can be closed")
    # priority 13: no ACTIVE lockout window for the project
    if any(w["project_id"] == sp["project_id"] and w["status"] == "ACTIVE"
           for w in db.lockout_windows.values()):
        raise ApiError(ERR_LOCKOUTS_OUTSTANDING, 409,
                       "an ACTIVE lockout window blocks safety plan closure")
    was_suspended = sp["status"] == "SUSPENDED"
    sp["status"] = "CLOSED"
    touch(sp)
    if was_suspended:
        project = db.projects[sp["project_id"]]
        project["hold_status"] = "CLEAR"
        touch(project)
    return success(safety_plan_json(sp))
