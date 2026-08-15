"""Inspector and Inspection endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_DATE_IN_PAST,
    ERR_FORBIDDEN_OWNER,
    ERR_INSPECTOR_NOT_CERTIFIED,
    ERR_INSPECTOR_WINDOW_CONFLICT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    raise_error,
)
from middleware import (
    ANY_ROLE,
    check_app_mutable,
    get_body,
    new_id,
    paginate,
    parse_iso_date,
    require_enum,
    require_fields,
    require_roles,
    require_str,
    validate_window,
)
from response import success_list, success_object
from services.domain import get_application, get_inspection, get_inspector, touch

bp = Blueprint("inspections", __name__)

CERTIFICATIONS = ("PRESSURE_TEST", "ROAD_CUT", "FINAL_SAFETY")
INSPECTION_TYPES = ("ROAD_CUT_RESTORATION", "PRESSURE_TEST", "FINAL_SAFETY")
# Certification member that gates each inspection type
TYPE_REQUIRED_CERT = {
    "ROAD_CUT_RESTORATION": "ROAD_CUT",
    "PRESSURE_TEST": "PRESSURE_TEST",
    "FINAL_SAFETY": "FINAL_SAFETY",
}


# --- Inspectors ----------------------------------------------------------------

@bp.route("/inspectors", methods=["POST"])
def create_inspector():
    require_roles("SystemAdmin")
    body = get_body()
    require_fields(body, "full_name", "certifications")
    certs = body["certifications"]
    if not isinstance(certs, list):
        raise_error(ERR_INVALID_REQUEST, "certifications must be an array")
    for c in certs:
        if c not in CERTIFICATIONS:
            raise_error(ERR_INVALID_REQUEST, f"Unknown certification: {c!r}")
    now = db.now_iso()
    inspector = {
        "id": new_id(),
        "full_name": require_str(body, "full_name"),
        "certifications": certs,
        "active": True,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.inspectors[inspector["id"]] = inspector
    return success_object(inspector, 201)


@bp.route("/inspectors/<iid>", methods=["GET"])
def get_one_inspector(iid):
    require_roles(*ANY_ROLE)
    return success_object(get_inspector(iid))


@bp.route("/inspectors", methods=["GET"])
def list_inspectors():
    require_roles(*ANY_ROLE)
    page, limit, offset, total = paginate(list(db.inspectors.values()))
    return success_list(page, limit, offset, total)


# --- Inspections ----------------------------------------------------------------

def _check_inspection_window(inspector_id, inspection_date, start_minute, end_minute, exclude_id=None):
    """Half-open overlap: conflict iff new.start < existing.end AND new.end > existing.start.
    Adjacency (end == start) is allowed. Applies vs SCHEDULED inspections of the same
    inspector on the same date."""
    for other in db.inspections.values():
        if other["inspector_id"] != inspector_id:
            continue
        if other["inspection_date"] != inspection_date:
            continue
        if other["status"] != "SCHEDULED":
            continue
        if other["id"] == exclude_id:
            continue
        if start_minute < other["end_minute"] and end_minute > other["start_minute"]:
            raise_error(ERR_INSPECTOR_WINDOW_CONFLICT, "Inspection window conflicts with an existing inspection")


def _validate_inspection_request(inspector, inspection_type, inspection_date, start_minute, end_minute, exclude_id=None):
    """Creation-time checks: date not past, inspector active, certification, window conflict."""
    idate = parse_iso_date(inspection_date, "inspection_date")
    if idate < db.today_date():
        raise_error(ERR_DATE_IN_PAST, "inspection_date must not be in the past")
    validate_window(start_minute, end_minute)
    if not inspector["active"]:
        raise_error(ERR_INVALID_STATE, "Inactive inspectors reject new inspections")
    required = TYPE_REQUIRED_CERT[inspection_type]
    if required not in inspector["certifications"]:
        raise_error(ERR_INSPECTOR_NOT_CERTIFIED, f"Inspector lacks the {required} certification")
    _check_inspection_window(inspector["id"], inspection_date, start_minute, end_minute, exclude_id=exclude_id)


@bp.route("/inspections", methods=["POST"])
def create_inspection():
    require_roles("PermitCoordinator")
    body = get_body()
    require_fields(
        body,
        "service_application_id",
        "inspector_id",
        "inspection_type",
        "inspection_date",
        "start_minute",
        "end_minute",
    )
    app = get_application(body["service_application_id"])
    inspector = get_inspector(body["inspector_id"])
    inspection_type = require_enum(body, "inspection_type", INSPECTION_TYPES)
    check_app_mutable(app)
    _validate_inspection_request(
        inspector, inspection_type, body["inspection_date"], body["start_minute"], body["end_minute"]
    )
    now = db.now_iso()
    inspection = {
        "id": new_id(),
        "service_application_id": app["id"],
        "inspector_id": inspector["id"],
        "inspection_type": inspection_type,
        "inspection_date": body["inspection_date"],
        "start_minute": body["start_minute"],
        "end_minute": body["end_minute"],
        "status": "SCHEDULED",
        "result_notes": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.inspections[inspection["id"]] = inspection
    return success_object(inspection, 201)


@bp.route("/inspections/<iid>", methods=["GET"])
def get_one_inspection(iid):
    require_roles(*ANY_ROLE)
    return success_object(get_inspection(iid))


@bp.route("/inspections", methods=["GET"])
def list_inspections():
    require_roles(*ANY_ROLE)
    records = list(db.inspections.values())
    inspector_id = request.args.get("inspector_id")
    app_id = request.args.get("service_application_id")
    status = request.args.get("status")
    if inspector_id is not None:
        records = [i for i in records if i["inspector_id"] == inspector_id]
    if app_id is not None:
        records = [i for i in records if i["service_application_id"] == app_id]
    if status is not None:
        records = [i for i in records if i["status"] == status]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)


@bp.route("/inspections/<iid>/record-result", methods=["POST"])
def record_result(iid):
    user_id, _ = require_roles("Inspector")
    inspection = get_inspection(iid)
    # Ownership: only the named inspector records the outcome
    if inspection["inspector_id"] != user_id:
        raise_error(ERR_FORBIDDEN_OWNER, "Only the assigned inspector may record the result")
    body = get_body()
    require_fields(body, "result")
    result = require_enum(body, "result", ("PASS", "FAIL"))
    app = get_application(inspection["service_application_id"])
    check_app_mutable(app)
    if inspection["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "Only SCHEDULED inspections can receive a result")
    inspection["status"] = "COMPLETED_PASS" if result == "PASS" else "COMPLETED_FAIL"
    if "notes" in body and body["notes"] is not None:
        inspection["result_notes"] = body["notes"]
    touch(inspection)
    return success_object(inspection)


@bp.route("/inspections/<iid>/cancel", methods=["POST"])
def cancel_inspection(iid):
    require_roles("PermitCoordinator")
    inspection = get_inspection(iid)
    app = get_application(inspection["service_application_id"])
    check_app_mutable(app)
    if inspection["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "Only SCHEDULED inspections can be cancelled")
    inspection["status"] = "CANCELLED"
    touch(inspection)
    return success_object(inspection)


@bp.route("/inspections/<iid>/reschedule", methods=["POST"])
def reschedule_inspection(iid):
    require_roles("PermitCoordinator")
    inspection = get_inspection(iid)
    app = get_application(inspection["service_application_id"])
    body = get_body()
    require_fields(body, "inspection_date", "start_minute", "end_minute")
    check_app_mutable(app)
    if inspection["status"] not in ("COMPLETED_FAIL", "EXPIRED"):
        raise_error(ERR_INVALID_STATE, "Only COMPLETED_FAIL or EXPIRED inspections can be rescheduled")
    inspector = get_inspector(inspection["inspector_id"])
    _validate_inspection_request(
        inspector,
        inspection["inspection_type"],
        body["inspection_date"],
        body["start_minute"],
        body["end_minute"],
        exclude_id=inspection["id"],
    )
    inspection["inspection_date"] = body["inspection_date"]
    inspection["start_minute"] = body["start_minute"]
    inspection["end_minute"] = body["end_minute"]
    inspection["status"] = "SCHEDULED"
    touch(inspection)
    return success_object(inspection)
