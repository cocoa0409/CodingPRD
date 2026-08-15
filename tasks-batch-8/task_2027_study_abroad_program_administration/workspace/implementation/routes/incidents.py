"""Incident endpoints."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import get_auth, require_role, check_student_ownership
from response import success_object, success_list
from utils import require_string, require_enum, parse_pagination
from errors import not_found, invalid_request, invalid_state, forbidden

bp = Blueprint("incidents", __name__)

SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
ALLOWED_TRANSITIONS = {
    "REPORTED": {"TRIAGED"},
    "TRIAGED": {"ESCALATED", "RESOLVED"},
    "ESCALATED": {"RESOLVED"},
}


@bp.route("/api/v1/incidents", methods=["POST"])
def create_incident():
    user_id, role = get_auth()
    require_role(role, ["Student", "ProgramCoordinator"])

    body = request.get_json(silent=True) or {}
    application_id = require_string(body, "application_id")
    severity = require_enum(body, "severity", SEVERITIES)
    description = require_string(body, "description")

    app = db.applications.get(application_id)
    if not app:
        raise not_found("Application not found")

    if role == "Student":
        check_student_ownership(user_id, role, app["student_id"])

    if app["status"] != "ABROAD":
        raise invalid_state("Application is not in ABROAD status")

    ts = now_iso()
    rec = {
        "id": new_id(),
        "application_id": app["id"],
        "severity": severity,
        "description": description,
        "reported_by": user_id,
        "status": "REPORTED",
        "resolution_notes": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.incidents[rec["id"]] = rec
    return success_object(rec, 201)


@bp.route("/api/v1/incidents", methods=["GET"])
def list_incidents():
    user_id, role = get_auth()
    require_role(role, ["SafetyOfficer", "ProgramCoordinator"])

    limit, offset = parse_pagination(request.args)
    application_id = request.args.get("application_id")
    status = request.args.get("status")

    items = list(db.incidents.values())
    if application_id is not None:
        items = [i for i in items if i["application_id"] == application_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]

    items.sort(key=lambda i: (i["created_at"], i["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(i) for i in page], limit, offset, total)


@bp.route("/api/v1/incidents/<id>", methods=["GET"])
def get_incident(id):
    user_id, role = get_auth()
    require_role(role, ["SafetyOfficer", "ProgramCoordinator"])

    rec = db.incidents.get(id)
    if not rec:
        raise not_found("Incident not found")
    return success_object(dict(rec), 200)


@bp.route("/api/v1/incidents/<id>/transition", methods=["POST"])
def transition_incident(id):
    user_id, role = get_auth()
    require_role(role, ["SafetyOfficer"])

    rec = db.incidents.get(id)
    if not rec:
        raise not_found("Incident not found")

    body = request.get_json(silent=True) or {}
    to_state = require_enum(body, "to_state", {"TRIAGED", "ESCALATED", "RESOLVED"})

    allowed = ALLOWED_TRANSITIONS.get(rec["status"], set())
    if to_state not in allowed:
        raise invalid_state(f"Incident cannot transition from {rec['status']} to {to_state}")

    if to_state == "RESOLVED":
        resolution_notes = body.get("resolution_notes")
        if resolution_notes is not None and not isinstance(resolution_notes, str):
            raise invalid_request("resolution_notes must be a string or null")
        rec["resolution_notes"] = resolution_notes

    rec["status"] = to_state
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(dict(rec), 200)
