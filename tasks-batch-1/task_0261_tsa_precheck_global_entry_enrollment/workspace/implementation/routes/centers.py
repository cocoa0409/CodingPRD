"""Enrollment centers and the bookable slot pool (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_SLOT_NOT_AVAILABLE
from middleware import require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    optional_int,
    order_by_created,
    paginate,
    parse_pagination,
    require_enum,
    require_fields,
    require_int,
    require_str,
    serialize,
    serialize_list,
    stamp_create,
    touch,
)
from services.lookups import get_or_404, get_or_referenced, parse_iso_utc

bp = Blueprint("centers", __name__)

CENTER_READ_ROLES = ["SchedulingAdmin", "EnrollmentOfficer", "Applicant"]
SLOT_READ_ROLES = ["SchedulingAdmin", "EnrollmentOfficer", "Applicant"]


# --- Enrollment Centers -------------------------------------------------------
@bp.route("/enrollment-centers", methods=["POST"])
def create_center():
    require_auth(["SchedulingAdmin"])
    body = get_body()
    require_fields(body, ["program_code", "name", "daily_interview_capacity"])
    program_code = require_enum(body, "program_code", ["PRECHECK", "GLOBAL_ENTRY"])
    name = require_str(body, "name")
    capacity = require_int(body, "daily_interview_capacity", minimum=1)
    buffer_minutes = optional_int(body, "buffer_minutes", default=0, minimum=0)
    lane_count = optional_int(body, "lane_count", default=1, minimum=1)

    rec = {
        "program_code": program_code,
        "name": name,
        "daily_interview_capacity": capacity,
        "buffer_minutes": buffer_minutes,
        "lane_count": lane_count,
        "status": "OPEN",
    }
    stamp_create(rec)
    db.enrollment_centers[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/enrollment-centers/<cid>", methods=["GET"])
def get_center(cid):
    require_auth(CENTER_READ_ROLES)
    rec = get_or_404(db.enrollment_centers, cid, "EnrollmentCenter")
    return ok_object(serialize(rec), 200)


@bp.route("/enrollment-centers/<cid>/suspend", methods=["POST"])
def suspend_center(cid):
    require_auth(["SchedulingAdmin"])
    rec = get_or_404(db.enrollment_centers, cid, "EnrollmentCenter")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return ok_object(serialize(rec), 200)


@bp.route("/enrollment-centers/<cid>/appointment-slots", methods=["GET"])
def list_center_slots(cid):
    require_auth(SLOT_READ_ROLES)
    get_or_404(db.enrollment_centers, cid, "EnrollmentCenter")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [s for s in db.appointment_slots.values() if s.get("center_id") == cid]
    if status is not None:
        items = [s for s in items if s.get("status") == status]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


# --- Appointment Slots --------------------------------------------------------
@bp.route("/appointment-slots", methods=["POST"])
def create_slot():
    require_auth(["SchedulingAdmin"])
    body = get_body()
    require_fields(body, ["center_id", "lane_index", "starts_at", "ends_at"])
    center_id = require_str(body, "center_id")
    lane_index = require_int(body, "lane_index", minimum=0)
    starts_raw = require_str(body, "starts_at")
    ends_raw = require_str(body, "ends_at")

    # FK existence (priority 4) before further schema checks on the FK target.
    center = get_or_referenced(db.enrollment_centers, center_id, "EnrollmentCenter")

    starts_dt = parse_iso_utc(starts_raw)
    ends_dt = parse_iso_utc(ends_raw)
    if starts_dt is None or ends_dt is None:
        raise APIError(ERR_INVALID_REQUEST, 422, "starts_at/ends_at must be ISO 8601 UTC datetimes")
    if ends_dt <= starts_dt:
        raise APIError(ERR_INVALID_REQUEST, 422, "ends_at must be strictly after starts_at")
    if lane_index >= center["lane_count"]:
        raise APIError(ERR_INVALID_REQUEST, 422, "lane_index must be < center.lane_count")

    rec = {
        "center_id": center_id,
        "lane_index": lane_index,
        "starts_at": db.iso(starts_dt),
        "ends_at": db.iso(ends_dt),
        "status": "AVAILABLE",
        "held_by_appointment_id": None,
    }
    stamp_create(rec)
    db.appointment_slots[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/appointment-slots/<sid>", methods=["GET"])
def get_slot(sid):
    require_auth(SLOT_READ_ROLES)
    rec = get_or_404(db.appointment_slots, sid, "AppointmentSlot")
    return ok_object(serialize(rec), 200)


@bp.route("/appointment-slots/<sid>/release", methods=["POST"])
def release_slot(sid):
    require_auth(["SchedulingAdmin"])
    rec = get_or_404(db.appointment_slots, sid, "AppointmentSlot")
    if rec["status"] != "AVAILABLE":
        raise APIError(ERR_SLOT_NOT_AVAILABLE, 409, "Slot is not AVAILABLE")
    rec["status"] = "RELEASED"
    touch(rec)
    return ok_object(serialize(rec), 200)
