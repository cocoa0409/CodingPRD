"""Appointment routes (booking with buffer/overlap/freeze, resolution)."""

from datetime import timedelta

from flask import Blueprint, request

import db
import domain
import serializers as ser
from auth import require_role, body
from envelope import success_object, success_list, paginate
from errors import (ApiError, invalid_request, invalid_state,
                    forbidden_ownership, ERR_NO_SHOW_FREEZE,
                    ERR_APPOINTMENT_CONFLICT)
from util import parse_iso
from validate import (new_record, touch, req_field, fk_or_404, get_or_404)

bp = Blueprint("appointments", __name__)

BUFFER = timedelta(minutes=domain.BUFFER_MINUTES)


@bp.post("/scheduling/appointments")
def book():
    user_id, role = require_role("Counselor", "Student")
    data = body()
    counselor_id = req_field(data, "counselor_id")
    student_id = req_field(data, "student_id")
    if not isinstance(counselor_id, str) or not isinstance(student_id, str):
        raise invalid_request("counselor_id and student_id must be strings")
    counselor = fk_or_404(db.counselors, counselor_id, "counselor_id")
    student = fk_or_404(db.students, student_id, "student_id")
    if role == "Student":
        if user_id != student["id"]:
            raise forbidden_ownership("Students may only book for themselves")
    else:
        if user_id != counselor["id"]:
            raise forbidden_ownership(
                "Counselors may only book their own appointments")
        if student["counselor_id"] != counselor["id"]:
            raise forbidden_ownership(
                "Counselors may only book caseload students")
    if domain.trailing_no_shows(student["id"]) >= domain.FREEZE_THRESHOLD:
        raise ApiError(ERR_NO_SHOW_FREEZE, 422,
                       "Student has 3 or more no-shows in the trailing 90 "
                       "days; booking is frozen")
    start_raw = req_field(data, "start_at")
    end_raw = req_field(data, "end_at")
    try:
        start = parse_iso(start_raw)
        end = parse_iso(end_raw)
    except ValueError:
        raise invalid_request("start_at and end_at must be ISO8601 timestamps")
    if end <= start:
        raise invalid_request("end_at must be after start_at")
    if start.date() != end.date():
        raise invalid_request("start_at and end_at must fall within the same "
                              "UTC day")
    for a in db.appointments.values():
        if a["state"] != "BOOKED":
            continue
        try:
            as_ = parse_iso(a["start_at"])
            ae = parse_iso(a["end_at"])
        except ValueError:
            continue
        if a["counselor_id"] == counselor["id"]:
            if not (end + BUFFER <= as_ or start >= ae + BUFFER):
                raise ApiError(ERR_APPOINTMENT_CONFLICT, 409,
                               "Counselor buffer (10 minutes) or overlap "
                               "violated")
        if a["student_id"] == student["id"]:
            if start < ae and as_ < end:
                raise ApiError(ERR_APPOINTMENT_CONFLICT, 409,
                               "Student is double-booked")
    appt = new_record()
    appt.update({
        "counselor_id": counselor["id"], "student_id": student["id"],
        "start_at": start_raw, "end_at": end_raw, "state": "BOOKED",
        "no_show_count_snapshot": domain.trailing_no_shows(student["id"]),
    })
    db.appointments[appt["id"]] = appt
    return success_object(ser.appointment(appt), 201)


@bp.get("/scheduling/appointments")
def list_appointments():
    require_role("Administrator", "Counselor", "Student")
    rows = list(db.appointments.values())
    for param in ("counselor_id", "student_id", "state"):
        v = request.args.get(param)
        if v is not None:
            rows = [a for a in rows if a[param] == v]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.appointment(a) for a in page],
                        limit, offset, total)


@bp.get("/scheduling/appointments/<aid>")
def get_appointment(aid):
    require_role("Administrator", "Counselor", "Student")
    return success_object(ser.appointment(get_or_404(db.appointments, aid)))


def _resolve(aid, counselor_only):
    user_id, role = require_role("Counselor", "Student") \
        if not counselor_only else require_role("Counselor")
    a = get_or_404(db.appointments, aid)
    if a["state"] != "BOOKED":
        raise invalid_state("Only BOOKED appointments can be resolved")
    if role == "Counselor":
        if user_id != a["counselor_id"]:
            raise forbidden_ownership("Only the attending counselor may do "
                                      "this")
    else:
        if user_id != a["student_id"]:
            raise forbidden_ownership("Only the attending student may do "
                                      "this")
    return a


@bp.post("/scheduling/appointments/<aid>/complete")
def complete(aid):
    a = _resolve(aid, counselor_only=True)
    a["state"] = "COMPLETED"
    a["version"] += 1
    touch(a)
    return success_object(ser.appointment(a))


@bp.post("/scheduling/appointments/<aid>/mark-no-show")
def mark_no_show(aid):
    a = _resolve(aid, counselor_only=True)
    a["state"] = "NO_SHOW"
    a["version"] += 1
    touch(a)
    return success_object(ser.appointment(a))


@bp.post("/scheduling/appointments/<aid>/cancel")
def cancel(aid):
    a = _resolve(aid, counselor_only=False)
    a["state"] = "CANCELLED"
    a["version"] += 1
    touch(a)
    return success_object(ser.appointment(a))
