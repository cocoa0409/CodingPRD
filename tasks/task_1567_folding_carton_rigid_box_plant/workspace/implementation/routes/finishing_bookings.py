"""FinishingBooking endpoints (PRD §3.6): padded closed windows, op gating."""

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_FINISHING_WINDOW_CONFLICT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LINE_UNAVAILABLE,
    ERR_OPERATION_ALREADY_BOOKED,
    ERR_OPERATION_NOT_REQUIRED,
    ERR_OPERATION_UNSUPPORTED,
    ERR_WINDOW_IN_PAST,
)
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    fk_exists,
    get_body,
    get_or_404,
    list_response,
    req_enum,
    req_str,
    ser_plain,
)
from util import parse_dt, touch

bp = Blueprint("finishing_bookings", __name__)

OPERATIONS = ("COAT", "FOIL", "EMBOSS")
OP_TO_FLAG = {"COAT": "finish_coat", "FOIL": "finish_foil", "EMBOSS": "finish_emboss"}


@bp.post("/plant/finishing-bookings")
def create_finishing_booking():
    authenticate(("FinishingOperator",))
    data = get_body()
    fk_exists(db.jobs, data, "job_id")
    fk_exists(db.finishing_lines, data, "line_id")

    job_id = req_str(data, "job_id")
    line_id = req_str(data, "line_id")
    operation = req_enum(data, "operation", OPERATIONS)
    start_utc = req_str(data, "start_utc")
    end_utc = req_str(data, "end_utc")
    start_dt = parse_dt(start_utc)
    end_dt = parse_dt(end_utc)
    if start_dt is None or end_dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "start_utc and end_utc must be ISO 8601 datetimes")

    job = db.jobs[job_id]
    line = db.finishing_lines[line_id]

    # Priority 6: job state
    if job["status"] not in ("IN_PRODUCTION", "FINISHING"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Finishing bookings require an IN_PRODUCTION or FINISHING job")

    # Priority 8: booking windows (past check, then padded closed overlap)
    if start_dt < db.clock["dt"]:
        raise ApiError(ERR_WINDOW_IN_PAST, 409,
                       "Booking start_utc is earlier than the plant logical clock")
    buffer = timedelta(minutes=line["setup_buffer_minutes"])
    new_start = start_dt - buffer
    new_end = end_dt
    for other in db.finishing_bookings.values():
        if other["line_id"] != line_id or other["status"] == "CANCELLED":
            continue
        other_start = parse_dt(other["start_utc"]) - buffer
        other_end = parse_dt(other["end_utc"])
        # Padded closed intervals: touching endpoints DO conflict.
        if new_start <= other_end and other_start <= new_end:
            raise ApiError(ERR_FINISHING_WINDOW_CONFLICT, 409,
                           "Padded window intersects a non-CANCELLED booking on this line")

    # Priority 9: referenced-entity state
    if line["status"] != "ACTIVE":
        raise ApiError(ERR_LINE_UNAVAILABLE, 409, "Finishing line is DOWN")
    if operation not in line["supported_ops"]:
        raise ApiError(ERR_OPERATION_UNSUPPORTED, 409,
                       "Line does not support operation %s" % operation)
    if not job[OP_TO_FLAG[operation]]:
        raise ApiError(ERR_OPERATION_NOT_REQUIRED, 409,
                       "Job does not require operation %s" % operation)

    # Priority 10: one non-CANCELLED booking per (job, operation)
    if any(fb["job_id"] == job_id and fb["operation"] == operation
           and fb["status"] != "CANCELLED"
           for fb in db.finishing_bookings.values()):
        raise ApiError(ERR_OPERATION_ALREADY_BOOKED, 409,
                       "A live booking for this job and operation already exists")

    rec = db.new_record()
    rec.update({
        "job_id": job_id,
        "line_id": line_id,
        "operation": operation,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "status": "SCHEDULED",
    })
    db.finishing_bookings[rec["id"]] = rec
    return ok_object(ser_plain(rec), 201)


@bp.get("/plant/finishing-bookings")
def list_finishing_bookings():
    authenticate(ALL_ROLES)
    return list_response(
        db.finishing_bookings.values(),
        ser_plain,
        [("job_id", "job_id", "str"),
         ("line_id", "line_id", "str"),
         ("status", "status", "str")],
    )


@bp.get("/plant/finishing-bookings/<bookingId>")
def get_finishing_booking(bookingId):
    authenticate(ALL_ROLES)
    return ok_object(ser_plain(get_or_404(db.finishing_bookings, bookingId)))


@bp.post("/plant/finishing-bookings/<bookingId>/complete")
def complete_finishing_booking(bookingId):
    authenticate(("FinishingOperator",))
    rec = get_or_404(db.finishing_bookings, bookingId)
    if rec["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a SCHEDULED booking can be completed")
    rec["status"] = "COMPLETED"
    touch(rec)
    return ok_object(ser_plain(rec))


@bp.post("/plant/finishing-bookings/<bookingId>/cancel")
def cancel_finishing_booking(bookingId):
    authenticate(("FinishingOperator",))
    rec = get_or_404(db.finishing_bookings, bookingId)
    if rec["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a SCHEDULED booking can be cancelled")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(ser_plain(rec))
