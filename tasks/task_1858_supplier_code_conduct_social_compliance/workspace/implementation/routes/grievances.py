"""Grievance endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, PROGRAM_STAFF_ROLES, get_pagination
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_GRIEVANCE_INVALID_STATE,
)
from services.utils import new_uuid
from services.scorecard import recompute_supplier_scorecard

bp = Blueprint("grievances", __name__)

CHANNELS = {"HOTLINE", "WORKER_COMMITTEE", "AUDIT_INTERVIEW"}
CATEGORIES = {"WAGES", "HARASSMENT", "FORCED_LABOR", "SAFETY", "RECRUITMENT_FEES", "OTHER"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
TRIAGE_ACTIONS = {"START_REVIEW", "ESCALATE", "RESOLVE"}


def serialize(g):
    return {
        "id": g["id"],
        "facility_id": g["facility_id"],
        "channel": g["channel"],
        "category": g["category"],
        "severity": g["severity"],
        "description": g["description"],
        "is_anonymized": g["is_anonymized"],
        "status": g["status"],
        "resolution_note": g.get("resolution_note"),
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def _get_supplier_for_grievance(g):
    facility = db.facilities.get(g["facility_id"])
    if not facility:
        return None
    return db.suppliers.get(facility["supplier_id"])


@bp.route("/grievances", methods=["POST"])
def create_grievance():
    require_roles("WorkerHotline")
    body = request.get_json(silent=True) or {}
    facility_id = body.get("facility_id")
    channel = body.get("channel")
    category = body.get("category")
    severity = body.get("severity")
    description = body.get("description")
    if not isinstance(facility_id, str) or not facility_id:
        raise_err(ERR_INVALID_REQUEST, "facility_id is required")
    if channel not in CHANNELS:
        raise_err(ERR_INVALID_REQUEST, f"channel must be one of {sorted(CHANNELS)}")
    if category not in CATEGORIES:
        raise_err(ERR_INVALID_REQUEST, f"category must be one of {sorted(CATEGORIES)}")
    if severity not in SEVERITIES:
        raise_err(ERR_INVALID_REQUEST, f"severity must be one of {sorted(SEVERITIES)}")
    if not isinstance(description, str) or not description:
        raise_err(ERR_INVALID_REQUEST, "description is required")
    facility = db.facilities.get(facility_id)
    if not facility:
        raise_err(ERR_NOT_FOUND, "facility not found")
    g = {
        "id": new_uuid(),
        "facility_id": facility_id,
        "channel": channel,
        "category": category,
        "severity": severity,
        "description": description,
        "is_anonymized": True,
        "status": "SUBMITTED",
        "resolution_note": None,
        "created_at": db.get_clock(),
        "updated_at": db.get_clock(),
        "version": 1,
    }
    db.grievances[g["id"]] = g
    if severity == "CRITICAL":
        supplier = _get_supplier_for_grievance(g)
        if supplier is not None:
            recompute_supplier_scorecard(supplier)
    return success_object(serialize(g), 201)


@bp.route("/grievances", methods=["GET"])
def list_grievances():
    require_roles(*PROGRAM_STAFF_ROLES)
    limit, offset = get_pagination()
    fid = request.args.get("facility_id")
    status_f = request.args.get("status")
    sev_f = request.args.get("severity")
    cat_f = request.args.get("category")
    items = list(db.grievances.values())
    if fid is not None:
        items = [g for g in items if g["facility_id"] == fid]
    if status_f is not None:
        items = [g for g in items if g["status"] == status_f]
    if sev_f is not None:
        items = [g for g in items if g["severity"] == sev_f]
    if cat_f is not None:
        items = [g for g in items if g["category"] == cat_f]
    items.sort(key=lambda g: g["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_array([serialize(g) for g in page], total, limit, offset)


@bp.route("/grievances/<gid>", methods=["GET"])
def get_grievance(gid):
    require_roles(*PROGRAM_STAFF_ROLES)
    g = db.grievances.get(gid)
    if not g:
        raise_err(ERR_NOT_FOUND, "grievance not found")
    return success_object(serialize(g))


@bp.route("/grievances/<gid>/triage", methods=["POST"])
def triage_grievance(gid):
    require_roles("ComplianceOfficer")
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    resolution_note = body.get("resolution_note")
    if action not in TRIAGE_ACTIONS:
        raise_err(ERR_INVALID_REQUEST, f"action must be one of {sorted(TRIAGE_ACTIONS)}")
    g = db.grievances.get(gid)
    if not g:
        raise_err(ERR_NOT_FOUND, "grievance not found")
    if action == "START_REVIEW":
        if g["status"] != "SUBMITTED":
            raise_err(ERR_GRIEVANCE_INVALID_STATE, f"grievance status is {g['status']}")
        g["status"] = "UNDER_REVIEW"
    elif action == "ESCALATE":
        if g["status"] != "UNDER_REVIEW":
            raise_err(ERR_GRIEVANCE_INVALID_STATE, f"grievance status is {g['status']}")
        g["status"] = "ESCALATED"
    else:  # RESOLVE
        if g["status"] not in ("UNDER_REVIEW", "ESCALATED"):
            raise_err(ERR_GRIEVANCE_INVALID_STATE, f"grievance status is {g['status']}")
        if not isinstance(resolution_note, str) or not resolution_note:
            raise_err(ERR_INVALID_REQUEST, "resolution_note is required for RESOLVE")
        g["status"] = "RESOLVED"
        g["resolution_note"] = resolution_note
    g["version"] += 1
    g["updated_at"] = db.get_clock()
    # Scorecard recompute on CRITICAL severity grievance state changes that affect unresolved count
    if g["severity"] == "CRITICAL":
        supplier = _get_supplier_for_grievance(g)
        if supplier is not None:
            recompute_supplier_scorecard(supplier)
    return success_object(serialize(g))


@bp.route("/grievances/<gid>/recruitment-fee-reviews", methods=["GET"])
def list_grievance_reviews(gid):
    require_roles(*PROGRAM_STAFF_ROLES)
    g = db.grievances.get(gid)
    if not g:
        raise_err(ERR_NOT_FOUND, "grievance not found")
    items = [r for r in db.recruitment_fee_reviews.values() if r.get("linked_grievance_id") == gid]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    # Use review serializer lazily (defined in reviews module)
    from routes.reviews import serialize_review
    return success_array([serialize_review(r) for r in page], total, limit, offset)
