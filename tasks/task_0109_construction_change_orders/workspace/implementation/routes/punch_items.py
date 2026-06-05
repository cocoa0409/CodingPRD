"""Punch-list-item endpoints (PRD §3.7)."""
from flask import Blueprint, request

import db
import helpers as h
from errors import err, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import authenticate, require_role
from response import success

bp = Blueprint("punch_items", __name__)

SEVERITIES = {"MINOR", "MAJOR"}


def _get_or_404(pid):
    p = db.punch_items.get(pid)
    if p is None:
        raise err(ERR_NOT_FOUND, "PunchListItem not found.")
    return p


@bp.post("/punch-items")
def create_punch_item():
    _uid, role = authenticate()
    require_role(role, {"Architect"})
    body = h.get_json()
    h.require_fields(body, ["project_id", "location", "description"])

    project_id = h.as_string(body["project_id"], "project_id")
    if db.projects.get(project_id) is None:
        raise err(ERR_NOT_FOUND, "Project not found.")
    location = h.as_string(body["location"], "location")
    description = h.as_string(body["description"], "description")
    severity = "MINOR"
    if body.get("severity") is not None:
        severity = h.as_enum(body["severity"], "severity", SEVERITIES)

    record = {
        "project_id": project_id,
        "location": location,
        "description": description,
        "severity": severity,
        "status": "OPEN",
    }
    db.stamp_create(record)
    db.punch_items[record["id"]] = record
    return success(h.punch_item_out(record), status=201)


@bp.get("/punch-items/<pid>")
def get_punch_item(pid):
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    return success(h.punch_item_out(_get_or_404(pid)))


@bp.get("/punch-items")
def list_punch_items():
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    limit, offset = h.parse_pagination()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    records = list(db.punch_items.values())
    if project_id:
        records = [r for r in records if r["project_id"] == project_id]
    if status:
        records = [r for r in records if r["status"] == status]
    page, meta = h.paginate(records, limit, offset)
    return success([h.punch_item_out(r) for r in page], pagination=meta)


@bp.post("/punch-items/<pid>/ready")
def ready_punch_item(pid):
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    p = _get_or_404(pid)
    if p["status"] not in ("OPEN", "REOPENED"):
        raise err(ERR_INVALID_STATE, "PunchListItem is not OPEN/REOPENED.")
    p["status"] = "READY_FOR_REVIEW"
    db.touch(p)
    return success(h.punch_item_out(p))


@bp.post("/punch-items/<pid>/verify")
def verify_punch_item(pid):
    _uid, role = authenticate()
    require_role(role, {"Architect"})
    p = _get_or_404(pid)
    if p["status"] != "READY_FOR_REVIEW":
        raise err(ERR_INVALID_STATE, "PunchListItem is not READY_FOR_REVIEW.")
    p["status"] = "VERIFIED"
    db.touch(p)
    return success(h.punch_item_out(p))


@bp.post("/punch-items/<pid>/reopen")
def reopen_punch_item(pid):
    _uid, role = authenticate()
    require_role(role, {"Architect"})
    p = _get_or_404(pid)
    if p["status"] not in ("READY_FOR_REVIEW", "VERIFIED"):
        raise err(ERR_INVALID_STATE, "PunchListItem is not READY_FOR_REVIEW/VERIFIED.")
    # Substantial completion is sticky: reopening does NOT revert the project.
    p["status"] = "REOPENED"
    db.touch(p)
    return success(h.punch_item_out(p))
