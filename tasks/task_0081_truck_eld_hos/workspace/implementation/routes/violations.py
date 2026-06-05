"""HOSViolation read + review lifecycle (PRD §3.5, §3.10)."""
from flask import Blueprint, request

import db
import errors
import model
import response
import serializers as ser
import validation as val
from middleware import get_auth, require_role
from paginate import paginate

bp = Blueprint("violations", __name__)

VIOLATION_TYPES = {"DRIVING_11H", "WINDOW_14H", "CYCLE_70H", "BREAK_30MIN"}
VIOLATION_STATUSES = {"OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"}


@bp.route("/eld/hos-violations/<id>", methods=["GET"])
def get_violation(id):
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin", "SafetyOfficer"})
    rec = db.violations.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Violation not found.")
    return response.object_response(ser.violation_view(rec), 200)


@bp.route("/eld/hos-violations", methods=["GET"])
def list_violations():
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin", "SafetyOfficer"})
    limit, offset = val.get_pagination()
    items = list(db.violations.values())
    driver_id = request.args.get("driver_id")
    trigger_event_id = request.args.get("trigger_event_id")
    violation_type = request.args.get("violation_type")
    status = request.args.get("status")
    if driver_id is not None:
        items = [r for r in items if r["driver_id"] == driver_id]
    if trigger_event_id is not None:
        items = [r for r in items if r["trigger_event_id"] == trigger_event_id]
    if violation_type is not None:
        items = [r for r in items if r["violation_type"] == violation_type]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return response.array_response([ser.violation_view(r) for r in page], limit, offset, total)


@bp.route("/eld/hos-violations/<id>/acknowledge", methods=["POST"])
def acknowledge(id):
    _, role = get_auth()
    require_role(role, {"SafetyOfficer"})
    rec = db.violations.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Violation not found.")
    if rec["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Violation is not OPEN.")
    rec["status"] = "ACKNOWLEDGED"
    model.touch(rec)
    return response.object_response(ser.violation_view(rec), 200)


@bp.route("/eld/hos-violations/<id>/reopen", methods=["POST"])
def reopen(id):
    _, role = get_auth()
    require_role(role, {"SafetyOfficer"})
    rec = db.violations.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Violation not found.")
    if rec["status"] != "ACKNOWLEDGED":
        raise errors.err(errors.ERR_INVALID_STATE, "Violation is not ACKNOWLEDGED.")
    rec["status"] = "OPEN"
    model.touch(rec)
    return response.object_response(ser.violation_view(rec), 200)


@bp.route("/eld/hos-violations/<id>/resolve", methods=["POST"])
def resolve(id):
    _, role = get_auth()
    require_role(role, {"SafetyOfficer"})
    rec = db.violations.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Violation not found.")
    if rec["status"] != "ACKNOWLEDGED":
        raise errors.err(errors.ERR_INVALID_STATE, "Violation is not ACKNOWLEDGED.")
    body = val.get_body()
    note = val.optional_str(body, "resolution_note")
    if note is None or note == "":
        raise errors.err(errors.ERR_ANNOTATION_REQUIRED, "resolution_note is required.")
    rec["status"] = "RESOLVED"
    rec["resolution_note"] = note
    model.touch(rec)
    return response.object_response(ser.violation_view(rec), 200)
