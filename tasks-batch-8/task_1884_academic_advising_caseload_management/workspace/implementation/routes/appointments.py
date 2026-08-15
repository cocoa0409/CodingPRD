"""Appointment endpoints: book, list, get, check-in, cancel, complete."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object, success_list
from services.common import (
    body, get_pagination_params, iso_z, paginate, parse_iso_datetime, require_fields,
    stamp_new, touch,
)
from services.calculations import (
    recompute_advisor_scheduled_minutes, recompute_student_requirement_and_clearance,
)

bp = Blueprint("appointments", __name__)

ROLE_READ = ("AdvisingDirector", "Advisor", "FrontDeskStaff")
CHECK_IN_WINDOW_MINUTES = 10


def appointment_public(a):
    return {
        "id": a["id"],
        "student_id": a["student_id"],
        "advisor_id": a["advisor_id"],
        "term_code": a["term_code"],
        "scheduled_start_at": a["scheduled_start_at"],
        "scheduled_end_at": a["scheduled_end_at"],
        "duration_minutes": a["duration_minutes"],
        "status": a["status"],
        "checked_in_at": a["checked_in_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/advising/appointments", methods=["POST"])
def create_appointment():
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["student_id", "advisor_id", "term_code",
                          "scheduled_start_at", "scheduled_end_at"])
    start = parse_iso_datetime(data["scheduled_start_at"])
    end = parse_iso_datetime(data["scheduled_end_at"])
    duration_seconds = (end - start).total_seconds()
    duration_minutes = int(duration_seconds // 60)
    if end <= start or duration_seconds < 15 * 60 or duration_seconds > 60 * 60:
        raise ApiError(
            errors.ERR_INVALID_APPOINTMENT_DURATION,
            "Appointment end must be strictly after start and duration must be within [15, 60] minutes",
            400,
        )
    require_role(role, ("FrontDeskStaff", "Advisor", "AdvisingDirector"))

    student = db.students.get(data["student_id"])
    if not student:
        raise ApiError(errors.ERR_STUDENT_NOT_FOUND, f"Student {data['student_id']} not found", 404)
    advisor = db.advisors.get(data["advisor_id"])
    if not advisor:
        raise ApiError(errors.ERR_ADVISOR_NOT_FOUND, f"Advisor {data['advisor_id']} not found", 404)

    # priority 7: overlap check (half-open [start, end) intersection)
    for appt in db.appointments.values():
        if appt["advisor_id"] != advisor["id"]:
            continue
        if appt["status"] not in ("SCHEDULED", "CHECKED_IN"):
            continue
        ex_start = parse_iso_datetime(appt["scheduled_start_at"])
        ex_end = parse_iso_datetime(appt["scheduled_end_at"])
        # half-open overlap: start < ex_end AND ex_start < end
        if start < ex_end and ex_start < end:
            raise ApiError(errors.ERR_APPOINTMENT_OVERLAP,
                           "Requested slot overlaps an existing appointment of this advisor", 409)

    # priority 9: cross-entity state
    if student["care_status"] != "ENROLLED":
        raise ApiError(errors.ERR_STUDENT_NOT_ENROLLED,
                       "Student must be ENROLLED to book an appointment", 409)
    if advisor["status"] != "ACTIVE":
        raise ApiError(errors.ERR_ADVISOR_NOT_ACTIVE, "Advisor is not ACTIVE", 409)

    appointment = stamp_new({
        "student_id": student["id"],
        "advisor_id": advisor["id"],
        "term_code": data["term_code"],
        "scheduled_start_at": iso_z(start),
        "scheduled_end_at": iso_z(end),
        "duration_minutes": duration_minutes,
        "status": "SCHEDULED",
        "checked_in_at": None,
    })
    db.appointments[appointment["id"]] = appointment
    recompute_advisor_scheduled_minutes(advisor["id"])
    return success_object(appointment_public(appointment), 201)


@bp.route("/advising/appointments", methods=["GET"])
def list_appointments():
    user_id, role = get_auth_context()
    require_role(role, ROLE_READ)
    limit, offset = get_pagination_params()
    items = list(db.appointments.values())
    student_id = request.args.get("student_id")
    advisor_id = request.args.get("advisor_id")
    status = request.args.get("status")
    term_code = request.args.get("term_code")
    if student_id is not None:
        items = [a for a in items if a["student_id"] == student_id]
    if advisor_id is not None:
        items = [a for a in items if a["advisor_id"] == advisor_id]
    if status is not None:
        if status not in ("SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"):
            raise ApiError(errors.ERR_VALIDATION, f"Invalid status filter: {status}", 400)
        items = [a for a in items if a["status"] == status]
    if term_code is not None:
        items = [a for a in items if a["term_code"] == term_code]
    page, total = paginate(items, limit, offset)
    return success_list([appointment_public(a) for a in page], limit, offset, total)


@bp.route("/advising/appointments/<appointmentId>", methods=["GET"])
def get_appointment(appointmentId):
    user_id, role = get_auth_context()
    require_role(role, ROLE_READ)
    appt = db.appointments.get(appointmentId)
    if not appt:
        raise ApiError(errors.ERR_APPOINTMENT_NOT_FOUND,
                       f"Appointment {appointmentId} not found", 404)
    return success_object(appointment_public(appt))


@bp.route("/advising/appointments/<appointmentId>/check-in", methods=["POST"])
def check_in(appointmentId):
    user_id, role = get_auth_context()
    require_role(role, ("FrontDeskStaff",))
    appt = db.appointments.get(appointmentId)
    if not appt:
        raise ApiError(errors.ERR_APPOINTMENT_NOT_FOUND,
                       f"Appointment {appointmentId} not found", 404)
    # priority 6: state
    if appt["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_APPOINTMENT_INVALID_STATE,
                       "Appointment must be SCHEDULED to check in", 409)
    # priority 8: temporal window [start-10min, start+10min] inclusive
    now = parse_iso_datetime(db.get_logical_clock_iso())
    start = parse_iso_datetime(appt["scheduled_start_at"])
    window_start = start - timedelta(minutes=CHECK_IN_WINDOW_MINUTES)
    window_end = start + timedelta(minutes=CHECK_IN_WINDOW_MINUTES)
    if now < window_start or now > window_end:
        raise ApiError(errors.ERR_OUTSIDE_CHECK_IN_WINDOW,
                       "Check-in is outside the allowed window", 409)
    appt["status"] = "CHECKED_IN"
    appt["checked_in_at"] = iso_z(now)
    touch(appt)
    recompute_advisor_scheduled_minutes(appt["advisor_id"])
    return success_object(appointment_public(appt))


@bp.route("/advising/appointments/<appointmentId>/cancel", methods=["POST"])
def cancel(appointmentId):
    user_id, role = get_auth_context()
    require_role(role, ("FrontDeskStaff", "Advisor", "AdvisingDirector"))
    appt = db.appointments.get(appointmentId)
    if not appt:
        raise ApiError(errors.ERR_APPOINTMENT_NOT_FOUND,
                       f"Appointment {appointmentId} not found", 404)
    if appt["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_APPOINTMENT_INVALID_STATE,
                       "Appointment must be SCHEDULED to cancel", 409)
    appt["status"] = "CANCELLED"
    touch(appt)
    recompute_advisor_scheduled_minutes(appt["advisor_id"])
    return success_object(appointment_public(appt))


@bp.route("/advising/appointments/<appointmentId>/complete", methods=["POST"])
def complete(appointmentId):
    user_id, role = get_auth_context()
    require_role(role, ("Advisor", "AdvisingDirector"))
    appt = db.appointments.get(appointmentId)
    if not appt:
        raise ApiError(errors.ERR_APPOINTMENT_NOT_FOUND,
                       f"Appointment {appointmentId} not found", 404)
    if appt["status"] != "CHECKED_IN":
        raise ApiError(errors.ERR_APPOINTMENT_INVALID_STATE,
                       "Appointment must be CHECKED_IN to complete", 409)
    # ownership: Advisor-role caller must be the appointment's advisor
    if role == "Advisor" and user_id != appt["advisor_id"]:
        raise ApiError(errors.ERR_NOT_ASSIGNED_ADVISOR,
                       "Only the appointment's own advisor may complete it", 403)
    appt["status"] = "COMPLETED"
    touch(appt)
    recompute_advisor_scheduled_minutes(appt["advisor_id"])
    student = db.students.get(appt["student_id"])
    if student and appt["term_code"] == student["current_term_code"]:
        recompute_student_requirement_and_clearance(student["id"])
    return success_object(appointment_public(appt))
