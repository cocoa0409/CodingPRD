"""Project endpoints: create/list/get/advance."""
from flask import Blueprint, request

import db
from errors import (ApiError, ERR_CHECKLIST_NOT_SIGNED_OFF, ERR_INVALID_STATE,
                    ERR_LOCKOUTS_OUTSTANDING, ERR_NO_EXECUTED_LIFT,
                    ERR_SAFETY_HOLD, ERR_SAFETY_PLAN_NOT_ACTIVE,
                    ERR_SITE_SURVEY_NOT_ACCEPTED)
from helpers import project_or_404, sorted_items, touch
from middleware import ROLES, require_roles
from response import success, success_list
from serialize import project_json
from util import new_id, now_iso
from validators import get_body, pagination, req_enum, req_int, req_num, req_str

bp = Blueprint("projects", __name__)


@bp.post("/v1/projects")
@require_roles("ProjectManager")
def create_project():
    body = get_body()
    name = req_str(body, "name")
    customer_name = req_str(body, "customer_name")
    site_address = req_str(body, "site_address")
    billing_mode = req_enum(body, "billing_mode", ("TM", "LUMP_SUM"))
    contract_amount_cents = req_int(body, "contract_amount_cents", gt=0)
    equipment_hourly_rate_cents = req_int(body, "equipment_hourly_rate_cents", ge=0)
    if "retainage_pct" in body and body["retainage_pct"] is not None:
        retainage_pct, _ = req_num(body, "retainage_pct", ge=0, le="0.20")
    else:
        retainage_pct = 0.10
    if "ot_basis" in body and body["ot_basis"] is not None:
        ot_basis = req_enum(body, "ot_basis", ("DAILY_OT", "WEEKLY_OT"))
    else:
        ot_basis = "DAILY_OT"
    ts = now_iso()
    p = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "name": name,
        "customer_name": customer_name,
        "site_address": site_address,
        "billing_mode": billing_mode,
        "contract_amount_cents": contract_amount_cents,
        "equipment_hourly_rate_cents": equipment_hourly_rate_cents,
        "retainage_pct": retainage_pct,
        "ot_basis": ot_basis,
        "work_status": "AWARDED",
        "hold_status": "CLEAR",
        "approved_rigging_plan_id": None,
        "approved_rigging_plan_revision": None,
        "_seq": db.next_seq(),
    }
    db.projects[p["id"]] = p
    return success(project_json(p), 201)


@bp.get("/v1/projects")
@require_roles(*ROLES)
def list_projects():
    limit, offset = pagination()
    ws = request.args.get("work_status")
    bm = request.args.get("billing_mode")
    items = list(db.projects.values())
    if ws is not None:
        items = [p for p in items if p["work_status"] == ws]
    if bm is not None:
        items = [p for p in items if p["billing_mode"] == bm]
    items = sorted_items(items)
    total = len(items)
    return success_list([project_json(p) for p in items[offset:offset + limit]],
                        limit, offset, total)


@bp.get("/v1/projects/<pid>")
@require_roles(*ROLES)
def get_project(pid):
    return success(project_json(project_or_404(pid)))


@bp.post("/v1/projects/<pid>/advance")
@require_roles("ProjectManager")
def advance_project(pid):
    p = project_or_404(pid)
    # state gate (priority 5)
    ws = p["work_status"]
    if ws == "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, 409, "project is COMPLETED (terminal)")
    # safety interlock (priority 8)
    if p["hold_status"] != "CLEAR":
        raise ApiError(ERR_SAFETY_HOLD, 409, "project is under SAFETY_HOLD")
    # per-hop referential gates (priorities 9-15)
    if ws == "AWARDED":
        if not any(sp["project_id"] == pid and sp["status"] == "ACTIVE"
                   for sp in db.safety_plans.values()):
            raise ApiError(ERR_SAFETY_PLAN_NOT_ACTIVE, 409,
                           "no ACTIVE safety plan for the project")
        p["work_status"] = "MOBILIZED"
    elif ws == "MOBILIZED":
        if not any(s["project_id"] == pid and s["status"] == "ACCEPTED"
                   for s in db.site_surveys.values()):
            raise ApiError(ERR_SITE_SURVEY_NOT_ACCEPTED, 409,
                           "no ACCEPTED site survey for the project")
        p["work_status"] = "INSTALLING"
    elif ws == "INSTALLING":
        if not any(l["project_id"] == pid and l["status"] == "EXECUTED"
                   for l in db.lift_permits.values()):
            raise ApiError(ERR_NO_EXECUTED_LIFT, 409,
                           "no EXECUTED lift permit for the project")
        if any(w["project_id"] == pid and w["status"] in ("SCHEDULED", "ACTIVE")
               for w in db.lockout_windows.values()):
            raise ApiError(ERR_LOCKOUTS_OUTSTANDING, 409,
                           "lockout windows remain SCHEDULED or ACTIVE")
        p["work_status"] = "COMMISSIONING"
    elif ws == "COMMISSIONING":
        if not any(c["project_id"] == pid and c["status"] == "SIGNED_OFF"
                   for c in db.checklists.values()):
            raise ApiError(ERR_CHECKLIST_NOT_SIGNED_OFF, 409,
                           "no SIGNED_OFF commissioning checklist for the project")
        p["work_status"] = "COMPLETED"
    touch(p)
    return success(project_json(p))
