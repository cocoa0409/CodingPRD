"""Staff members and training records."""
from flask import Blueprint, request

from db import db, create_record, now, touch
from middleware import body, opt_bool, req_enum, req_str, require_roles
from response import success
from routes import list_response
from services import (STAFF_ROLES, TRAINING_TOPICS, TRAINING_VALIDITY_YEARS,
                      current_training_status, get_school, get_staff,
                      get_training_record, posture_gate, recompute_posture,
                      staff_out, training_out)
from util import add_calendar_years, parse_dt

bp = Blueprint("staff", __name__)

STAFF_READERS = ("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher")


@bp.post("/staff-members")
@require_roles("District504Director", "SchoolPrincipal")
def create_staff():
    d = body()
    school = get_school(req_str(d, "school_id"))
    posture_gate(school)
    rec = create_record(db.staff, {
        "school_id": school["id"],
        "staff_external_ref": req_str(d, "staff_external_ref"),
        "full_name": req_str(d, "full_name"),
        "staff_role": req_enum(d, "staff_role", STAFF_ROLES),
        "is_active": opt_bool(d, "is_active", True),
        "current_training_status": "UNTRAINED",
    })
    # A new active, untrained staff member changes training coverage.
    recompute_posture(school)
    return success(staff_out(rec), 201)


@bp.get("/staff-members")
@require_roles(*STAFF_READERS)
def list_staff():
    items = list(db.staff.values())
    school_id = request.args.get("school_id")
    staff_role = request.args.get("staff_role")
    is_active = request.args.get("is_active")
    if school_id is not None:
        items = [s for s in items if s["school_id"] == school_id]
    if staff_role is not None:
        items = [s for s in items if s["staff_role"] == staff_role]
    if is_active is not None:
        from middleware import parse_bool_filter
        flag = parse_bool_filter("is_active")
        items = [s for s in items if s.get("is_active", True) == flag]
    return list_response(items, staff_out)


@bp.get("/staff-members/<staffId>")
@require_roles(*STAFF_READERS)
def get_staff_detail(staffId):
    return success(staff_out(get_staff(staffId)), 200)


@bp.post("/training-records")
@require_roles("District504Director", "SchoolPrincipal", "Section504Coordinator")
def create_training_record():
    d = body()
    staff = get_staff(req_str(d, "staff_id"))
    school = get_school(staff["school_id"])
    posture_gate(school)
    topic = req_enum(d, "training_topic", TRAINING_TOPICS)
    trained_at = parse_dt(d.get("trained_at"), "trained_at") if "trained_at" in d and d["trained_at"] is not None else None
    if trained_at is None:
        from errors import ApiError, ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "Field 'trained_at': is required")
    expires_at = add_calendar_years(trained_at, TRAINING_VALIDITY_YEARS)
    rec = create_record(db.training_records, {
        "staff_id": staff["id"],
        "training_topic": topic,
        "trained_at": trained_at,
        "expires_at": expires_at,
        "training_status": "CURRENT" if now() < expires_at else "EXPIRED",
    })
    # Recompute the staff member's stored status; bump version if it changed.
    new_status = current_training_status(staff)
    if staff.get("current_training_status") != new_status:
        staff["current_training_status"] = new_status
        touch(staff)
    # Coverage changed -> posture may move.
    recompute_posture(school)
    return success(training_out(rec), 201)


@bp.get("/training-records")
@require_roles(*STAFF_READERS)
def list_training_records():
    items = list(db.training_records.values())
    staff_id = request.args.get("staff_id")
    topic = request.args.get("training_topic")
    if staff_id is not None:
        items = [r for r in items if r["staff_id"] == staff_id]
    if topic is not None:
        items = [r for r in items if r["training_topic"] == topic]
    return list_response(items, training_out)


@bp.get("/training-records/<recordId>")
@require_roles(*STAFF_READERS)
def get_training_record_detail(recordId):
    return success(training_out(get_training_record(recordId)), 200)
