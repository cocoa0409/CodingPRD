"""Appointment endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import common
import errors
import services
from middleware import require_roles
from response import success

ALL_ROLES = ("ShopManager", "BridalConsultant", "Seamstress", "FinanceClerk")
NON_TERMINAL = {"BOOKED", "CHECKED_IN"}

bp = Blueprint("appointments", __name__)


def _release_held_bookings_for_appointment(appointment_id):
    """Release every HELD fitting-room booking attached to an appointment."""
    for b in db.fitting_room_bookings.values():
        if b["appointment_id"] == appointment_id and b["status"] == "HELD":
            b["status"] = "RELEASED"
            db.touch(b)


@bp.route("/appointments", methods=["POST"])
@require_roles("BridalConsultant", "ShopManager")
def create_appointment():
    body = common.get_body()
    # Existence: stylist_id FK first (declaration order), then bridal_party_id.
    stylist_id = common.as_str(body, "stylist_id")
    stylist = services.get_stylist(stylist_id)
    appointment_type = common.as_enum(body, "appointment_type", {"CONSULTATION", "FITTING"})
    start_at = common.parse_datetime_str(body, "start_at")
    end_at = common.parse_datetime_str(body, "end_at")
    bridal_party_id = body.get("bridal_party_id")
    if bridal_party_id is not None:
        services.get_party(bridal_party_id)

    start_epoch = common.parse_iso_to_epoch(start_at)
    end_epoch = common.parse_iso_to_epoch(end_at)
    if not (end_epoch > start_epoch):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "end_at must be strictly after start_at")

    # Double-booking guard with cleanup buffer (PRD §3.2). Closed-on-start,
    # buffered-on-end. The buffer belongs to this stylist; apply it to whichever
    # side ends first so the full buffer must elapse after the earlier end.
    buffer_seconds = stylist["turnaround_buffer_minutes"] * 60
    for other in db.appointments.values():
        if other["stylist_id"] != stylist_id:
            continue
        if other["status"] not in NON_TERMINAL:
            continue
        o_start = common.parse_iso_to_epoch(other["start_at"])
        o_end = common.parse_iso_to_epoch(other["end_at"])
        # Overlap with the existing appointment's end inflated by the buffer,
        # and the candidate's end inflated by the buffer (symmetric back-to-back).
        if start_epoch < (o_end + buffer_seconds) and o_start < (end_epoch + buffer_seconds):
            errors.raise_error(
                errors.ERR_STYLIST_DOUBLE_BOOKED, "Stylist is double-booked"
            )

    obj = {
        "id": db.new_id(),
        "stylist_id": stylist_id,
        "bridal_party_id": bridal_party_id,
        "appointment_type": appointment_type,
        "start_at": start_at,
        "end_at": end_at,
        "status": "BOOKED",
    }
    db.stamp_create(obj)
    db.appointments[obj["id"]] = obj
    return success(common.serialize(obj), status=201)


@bp.route("/appointments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_appointments():
    limit, offset = common.paginate(request.args)
    rows = list(db.appointments.values())
    stylist_id = request.args.get("stylist_id")
    bridal_party_id = request.args.get("bridal_party_id")
    if stylist_id is not None:
        rows = [a for a in rows if a["stylist_id"] == stylist_id]
    if bridal_party_id is not None:
        rows = [a for a in rows if a.get("bridal_party_id") == bridal_party_id]
    window, meta = common.page_slice(rows, limit, offset)
    return success([common.serialize(o) for o in window], pagination=meta)


@bp.route("/appointments/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_appointment(aid):
    obj = services.get_appointment(aid)
    return success(common.serialize(obj))


@bp.route("/appointments/<aid>/check-in", methods=["POST"])
@require_roles("BridalConsultant")
def check_in(aid):
    obj = services.get_appointment(aid)
    if obj["status"] != "BOOKED":
        errors.raise_error(errors.ERR_APPOINTMENT_NOT_BOOKED, "Appointment is not BOOKED")
    stylist = db.stylists.get(obj["stylist_id"])
    if stylist is None or not stylist["active"]:
        errors.raise_error(errors.ERR_STYLIST_INACTIVE, "Stylist is inactive")
    obj["status"] = "CHECKED_IN"
    db.touch(obj)
    return success(common.serialize(obj))


@bp.route("/appointments/<aid>/revert-check-in", methods=["POST"])
@require_roles("BridalConsultant")
def revert_check_in(aid):
    obj = services.get_appointment(aid)
    if obj["status"] != "CHECKED_IN":
        errors.raise_error(errors.ERR_APPOINTMENT_NOT_CHECKED_IN, "Appointment is not CHECKED_IN")
    obj["status"] = "BOOKED"
    db.touch(obj)
    return success(common.serialize(obj))


@bp.route("/appointments/<aid>/complete", methods=["POST"])
@require_roles("BridalConsultant")
def complete_appointment(aid):
    obj = services.get_appointment(aid)
    if obj["status"] != "CHECKED_IN":
        errors.raise_error(errors.ERR_APPOINTMENT_NOT_CHECKED_IN, "Appointment is not CHECKED_IN")
    obj["status"] = "COMPLETED"
    db.touch(obj)
    _release_held_bookings_for_appointment(aid)
    return success(common.serialize(obj))


@bp.route("/appointments/<aid>/cancel", methods=["POST"])
@require_roles("BridalConsultant", "ShopManager")
def cancel_appointment(aid):
    obj = services.get_appointment(aid)
    if obj["status"] != "BOOKED":
        errors.raise_error(errors.ERR_APPOINTMENT_NOT_CANCELLABLE, "Appointment is not BOOKED")
    obj["status"] = "CANCELLED"
    db.touch(obj)
    _release_held_bookings_for_appointment(aid)
    return success(common.serialize(obj))


@bp.route("/appointments/<aid>/mark-no-show", methods=["POST"])
@require_roles("ShopManager")
def mark_no_show(aid):
    obj = services.get_appointment(aid)
    if obj["status"] != "BOOKED":
        errors.raise_error(errors.ERR_APPOINTMENT_NOT_BOOKED, "Appointment is not BOOKED")
    obj["status"] = "NO_SHOW"
    db.touch(obj)
    _release_held_bookings_for_appointment(aid)
    return success(common.serialize(obj))
