"""Work orders: report, list, get, drive lifecycle with habitability + SoD."""

from flask import Blueprint

import db
from errors import err
from middleware import require_roles, get_auth
from response import success_object, success_list
from services import core
from validate import (
    get_body, require_string, require_enum, optional_string,
    parse_pagination, get_filter, sort_and_paginate,
)

bp = Blueprint("work_orders", __name__)

CATEGORIES = {"PLUMBING", "ELECTRICAL", "STRUCTURAL", "PEST", "APPLIANCE", "OTHER"}
SEVERITIES = {"CRITICAL", "MAJOR", "MINOR"}
WO_TARGETS = {"TRIAGED", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "VERIFIED", "REOPENED", "CLOSED", "CANCELLED"}


def _view(w):
    return {
        "id": w["id"],
        "unit_id": w["unit_id"],
        "complaint_id": w["complaint_id"],
        "category": w["category"],
        "severity": w["severity"],
        "description": w["description"],
        "status": w["status"],
        "assignee_name": w["assignee_name"],
        "completed_by": w["completed_by"],
        "verified_by": w["verified_by"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


@bp.route("/work-orders", methods=["POST"])
def create_work_order():
    require_roles("OperatorAdmin", "SiteManager", "MaintenanceLead")
    body = get_body()
    unit_id = require_string(body, "unit_id")
    complaint_id = body.get("complaint_id")
    if complaint_id is not None and not isinstance(complaint_id, str):
        raise err("ERR_INVALID_REQUEST", "complaint_id must be a string")
    category = require_enum(body, "category", CATEGORIES)
    severity = require_enum(body, "severity", SEVERITIES)
    description = require_string(body, "description")

    unit = db.units.get(unit_id)
    if unit is None:
        raise err("ERR_UNIT_NOT_FOUND")
    if complaint_id is not None and db.complaints.get(complaint_id) is None:
        raise err("ERR_NOT_FOUND", "complaint_id does not exist")
    if unit["status"] == "DECOMMISSIONED":
        raise err("ERR_INVALID_STATE", "Cannot create a work order against a DECOMMISSIONED unit")

    now = db.now_ts()
    w = {
        "id": db.new_id(),
        "unit_id": unit_id,
        "complaint_id": complaint_id,
        "category": category,
        "severity": severity,
        "description": description,
        "status": "REPORTED",
        "assignee_name": None,
        "completed_by": None,
        "verified_by": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.work_orders[w["id"]] = w
    # CRITICAL severity immediately puts the unit on HABITABILITY_HOLD
    # (unless CONDEMNED/DECOMMISSIONED); recompute handles both hold and posture.
    core.recompute_unit_scores_and_hold(unit_id)
    return success_object(_view(w), status=201)


@bp.route("/work-orders", methods=["GET"])
def list_work_orders():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.work_orders.values())
    unit_f = get_filter("unit_id")
    complaint_f = get_filter("complaint_id")
    status_f = get_filter("status")
    severity_f = get_filter("severity")
    if unit_f is not None:
        items = [w for w in items if w["unit_id"] == unit_f]
    if complaint_f is not None:
        items = [w for w in items if w.get("complaint_id") == complaint_f]
    if status_f is not None:
        items = [w for w in items if w["status"] == status_f]
    if severity_f is not None:
        items = [w for w in items if w["severity"] == severity_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view(w) for w in page], total, limit, offset)


@bp.route("/work-orders/<wid>", methods=["GET"])
def get_work_order(wid):
    get_auth()
    w = db.work_orders.get(wid)
    if w is None:
        raise err("ERR_WORK_ORDER_NOT_FOUND")
    return success_object(_view(w))


@bp.route("/work-orders/<wid>", methods=["PUT"])
def drive_work_order(wid):
    user_id, role = require_roles("MaintenanceLead", "SiteManager")
    body = get_body()
    target = require_enum(body, "status", WO_TARGETS)
    w = db.work_orders.get(wid)
    if w is None:
        raise err("ERR_WORK_ORDER_NOT_FOUND")
    current = w["status"]
    now = db.now_ts()

    # Role/transition permission (priority 2).
    if target in ("TRIAGED", "ASSIGNED", "IN_PROGRESS", "COMPLETED"):
        if role != "MaintenanceLead":
            raise err("ERR_INSUFFICIENT_PERMISSIONS")
    elif target in ("VERIFIED", "REOPENED", "CLOSED"):
        if role != "SiteManager":
            raise err("ERR_INSUFFICIENT_PERMISSIONS")
    elif target == "CANCELLED":
        pass  # both MaintenanceLead and SiteManager allowed

    # Segregation of duties (priority 6) ahead of state validity.
    if target == "VERIFIED" and current == "COMPLETED":
        if w.get("completed_by") is not None and user_id == w["completed_by"]:
            raise err("ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    # State machine from-state validity (priority 7).
    allowed = {
        "REPORTED": {"TRIAGED", "CANCELLED"},
        "TRIAGED": {"ASSIGNED", "CANCELLED"},
        "ASSIGNED": {"IN_PROGRESS", "CANCELLED"},
        "IN_PROGRESS": {"COMPLETED", "CANCELLED"},
        "COMPLETED": {"VERIFIED", "REOPENED"},
        "VERIFIED": {"CLOSED"},
        "REOPENED": {"ASSIGNED", "CANCELLED"},
        "CLOSED": set(),
        "CANCELLED": set(),
    }
    if target not in allowed.get(current, set()):
        raise err("ERR_INVALID_STATE", f"Cannot move work order from {current} to {target}")

    if target == "ASSIGNED":
        assignee = body.get("assignee_name")
        if assignee is None or not isinstance(assignee, str) or not assignee:
            raise err("ERR_INVALID_REQUEST", "assignee_name is required on ASSIGNED")
        w["assignee_name"] = assignee

    w["status"] = target
    if target == "COMPLETED":
        w["completed_by"] = user_id
    if target == "VERIFIED":
        w["verified_by"] = user_id
    w["updated_at"] = now

    # Habitability-affecting transitions recompute scores/hold/posture.
    if target in ("VERIFIED", "REOPENED", "CLOSED", "CANCELLED"):
        core.recompute_unit_scores_and_hold(w["unit_id"])
    else:
        # Non score-affecting transitions still recompute posture per PRD for
        # create/verify/reopen/close/cancel; posture only changes via the above,
        # but keep posture fresh regardless.
        unit = db.units.get(w["unit_id"])
        if unit is not None:
            core.recompute_site_posture(unit["site_id"])

    return success_object(_view(w))
