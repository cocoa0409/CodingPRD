"""Appointment booking and interview lifecycle (PRD §3.5).

Booking is OCC-guarded on Application.version. Capacity rules: same-lane
buffer-expanded overlap (ERR_SLOT_OVERLAP) and daily capacity per center per UTC
date (ERR_DAILY_CAPACITY_EXCEEDED). A CLEARED check carries the application from
VETTING to INTERVIEW_SCHEDULED on booking.
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    APIError,
    ERR_APPOINTMENT_NOT_ELAPSED,
    ERR_BIOMETRICS_NOT_ACCEPTED,
    ERR_CENTER_SUSPENDED,
    ERR_DAILY_CAPACITY_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_SLOT_NOT_AVAILABLE,
    ERR_SLOT_OVERLAP,
    ERR_STALE_VERSION,
)
from middleware import require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    order_by_created,
    paginate,
    parse_pagination,
    require_fields,
    require_int,
    require_str,
    serialize,
    serialize_list,
    stamp_create,
    touch,
)
from services.audit import write_audit
from services.lookups import get_or_404, parse_iso_utc

bp = Blueprint("appointments", __name__)

APPT_READ_ROLES = ["SchedulingAdmin", "EnrollmentOfficer", "Applicant"]
BOOK_ROLES = ["Applicant", "SchedulingAdmin"]


# --- book ---------------------------------------------------------------------
@bp.route("/appointments", methods=["POST"])
def book():
    require_auth(BOOK_ROLES)
    body = get_body()
    require_fields(body, ["application_id", "slot_id", "expected_application_version"])
    application_id = require_str(body, "application_id")
    slot_id = require_str(body, "slot_id")
    expected = require_int(body, "expected_application_version")

    # Body-FK existence (priority 4).
    app = db.applications.get(application_id)
    if app is None:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 404, "application_id does not exist")
    slot = db.appointment_slots.get(slot_id)
    if slot is None:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 404, "slot_id does not exist")

    # OCC (priority 6) — before state/business checks (PRD §2.9).
    if expected != app["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "expected_application_version mismatch")

    center = db.enrollment_centers.get(slot["center_id"])

    # Center OPEN (priority 12).
    if center is not None and center.get("status") != "OPEN":
        raise APIError(ERR_CENTER_SUSPENDED, 409, "Enrollment center is suspended")

    # Slot AVAILABLE (priority 13).
    if slot["status"] != "AVAILABLE":
        raise APIError(ERR_SLOT_NOT_AVAILABLE, 409, "Target slot is not AVAILABLE")

    slot_start = parse_iso_utc(slot["starts_at"])
    slot_end = parse_iso_utc(slot["ends_at"])
    buffer_minutes = center.get("buffer_minutes", 0) if center is not None else 0

    # Same-lane buffer-expanded overlap (priority 14).
    buf = timedelta(minutes=buffer_minutes)
    req_lo = slot_start - buf
    req_hi = slot_end + buf
    for appt in db.appointments.values():
        if appt.get("status") != "CONFIRMED":
            continue
        if appt.get("center_id") != slot["center_id"]:
            continue
        other_slot = db.appointment_slots.get(appt.get("slot_id"))
        if other_slot is None or other_slot.get("lane_index") != slot.get("lane_index"):
            continue
        o_start = parse_iso_utc(appt["starts_at"])
        o_end = parse_iso_utc(appt["ends_at"])
        # Half-open intervals overlap iff req_lo < o_end and o_start < req_hi.
        if req_lo < o_end and o_start < req_hi:
            raise APIError(ERR_SLOT_OVERLAP, 409, "Same-lane buffer-expanded overlap")

    # Daily capacity (priority 15).
    if center is not None:
        target_date = slot_start.date()
        used = 0
        for appt in db.appointments.values():
            if (appt.get("center_id") == slot["center_id"]
                    and appt.get("status") == "CONFIRMED"):
                a_start = parse_iso_utc(appt["starts_at"])
                if a_start is not None and a_start.date() == target_date:
                    used += 1
        if used >= center["daily_interview_capacity"]:
            raise APIError(ERR_DAILY_CAPACITY_EXCEEDED, 409, "Daily interview capacity exceeded")

    appt = {
        "application_id": application_id,
        "slot_id": slot_id,
        "center_id": slot["center_id"],
        "starts_at": slot["starts_at"],
        "ends_at": slot["ends_at"],
        "status": "CONFIRMED",
    }
    stamp_create(appt)
    db.appointments[appt["id"]] = appt

    slot["status"] = "BOOKED"
    slot["held_by_appointment_id"] = appt["id"]
    touch(slot)

    # If the background check is CLEARED, advance VETTING -> INTERVIEW_SCHEDULED.
    bc = _the_check(application_id)
    if app["status"] == "VETTING" and bc is not None and bc["status"] == "CLEARED":
        app["status"] = "INTERVIEW_SCHEDULED"
        touch(app)
        write_audit(application_id, "INTERVIEW_SCHEDULED", "Appointment booked; interview scheduled")
    else:
        touch(app)
        write_audit(application_id, "APPOINTMENT_BOOKED", "Appointment booked")

    return ok_object(serialize(appt), 201)


# --- reads --------------------------------------------------------------------
@bp.route("/applications/<app_id>/appointments", methods=["GET"])
def list_application_appointments(app_id):
    require_auth(APPT_READ_ROLES)
    get_or_404(db.applications, app_id, "Application")
    limit, offset = parse_pagination()
    items = [a for a in db.appointments.values() if a.get("application_id") == app_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.route("/appointment-slots/<sid>/appointments", methods=["GET"])
def list_slot_appointments(sid):
    require_auth(APPT_READ_ROLES)
    get_or_404(db.appointment_slots, sid, "AppointmentSlot")
    limit, offset = parse_pagination()
    items = [a for a in db.appointments.values() if a.get("slot_id") == sid]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.route("/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    require_auth(APPT_READ_ROLES)
    rec = get_or_404(db.appointments, aid, "Appointment")
    return ok_object(serialize(rec), 200)


# --- cancel -------------------------------------------------------------------
@bp.route("/appointments/<aid>/cancel", methods=["POST"])
def cancel(aid):
    require_auth(["Applicant", "SchedulingAdmin"])
    appt = get_or_404(db.appointments, aid, "Appointment")
    if appt["status"] != "CONFIRMED":
        raise APIError(ERR_INVALID_STATE, 409, "Appointment must be CONFIRMED to cancel")
    appt["status"] = "CANCELLED"
    touch(appt)
    _free_slot(appt)
    _revert_application_if_scheduled(appt)
    return ok_object(serialize(appt), 200)


# --- no-show ------------------------------------------------------------------
@bp.route("/appointments/<aid>/no-show", methods=["POST"])
def no_show(aid):
    require_auth(["EnrollmentOfficer"])
    appt = get_or_404(db.appointments, aid, "Appointment")
    if appt["status"] != "CONFIRMED":
        raise APIError(ERR_INVALID_STATE, 409, "Appointment must be CONFIRMED to mark no-show")
    ends = parse_iso_utc(appt["ends_at"])
    if ends is not None and db.clock.now() < ends:
        raise APIError(ERR_APPOINTMENT_NOT_ELAPSED, 409, "Appointment window has not elapsed")
    appt["status"] = "NO_SHOW"
    touch(appt)
    _free_slot(appt)
    _revert_application_if_scheduled(appt)
    return ok_object(serialize(appt), 200)


# --- complete -----------------------------------------------------------------
@bp.route("/appointments/<aid>/complete", methods=["POST"])
def complete(aid):
    require_auth(["EnrollmentOfficer"])
    appt = get_or_404(db.appointments, aid, "Appointment")
    if appt["status"] != "CONFIRMED":
        raise APIError(ERR_INVALID_STATE, 409, "Appointment must be CONFIRMED to complete")
    # Requires an ACCEPTED biometric capture for the appointment.
    has_accepted = any(
        bc.get("appointment_id") == aid and bc.get("status") == "ACCEPTED"
        for bc in db.biometric_captures.values()
    )
    if not has_accepted:
        raise APIError(ERR_BIOMETRICS_NOT_ACCEPTED, 409, "No ACCEPTED biometric capture for appointment")
    appt["status"] = "COMPLETED"
    touch(appt)
    # Slot stays BOOKED. Carry application INTERVIEW_SCHEDULED -> INTERVIEW_COMPLETE.
    app = db.applications.get(appt["application_id"])
    if app is not None and app["status"] == "INTERVIEW_SCHEDULED":
        app["status"] = "INTERVIEW_COMPLETE"
        touch(app)
        write_audit(app["id"], "INTERVIEW_COMPLETE", "Interview completed")
    return ok_object(serialize(appt), 200)


# --- helpers ------------------------------------------------------------------
def _free_slot(appt: dict) -> None:
    slot = db.appointment_slots.get(appt.get("slot_id"))
    if slot is not None and slot.get("status") == "BOOKED":
        slot["status"] = "AVAILABLE"
        slot["held_by_appointment_id"] = None
        touch(slot)


def _revert_application_if_scheduled(appt: dict) -> None:
    app = db.applications.get(appt.get("application_id"))
    if app is not None:
        if app["status"] == "INTERVIEW_SCHEDULED":
            app["status"] = "VETTING"
        touch(app)


def _the_check(app_id: str):
    for bc in db.background_checks.values():
        if bc.get("application_id") == app_id:
            return bc
    return None
