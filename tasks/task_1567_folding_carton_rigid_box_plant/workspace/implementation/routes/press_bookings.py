"""PressBooking endpoints (PRD §3.5): half-open windows, capacity, completion cascade."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_INSUFFICIENT_BOARD_STOCK,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PRESS_TYPE_MISMATCH,
    ERR_PRESS_UNAVAILABLE,
    ERR_PRESS_WINDOW_CONFLICT,
    ERR_SHEET_EXCEEDS_CAPACITY,
    ERR_WINDOW_IN_PAST,
)
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    available_sheets,
    fk_exists,
    get_body,
    get_or_404,
    list_response,
    locked_plan_for,
    req_int,
    req_str,
    ser_plain,
)
from util import parse_dt, touch

bp = Blueprint("press_bookings", __name__)


@bp.post("/plant/press-bookings")
def create_press_booking():
    authenticate(("PressOperator",))
    data = get_body()
    fk_exists(db.jobs, data, "job_id")
    fk_exists(db.presses, data, "press_id")

    job_id = req_str(data, "job_id")
    press_id = req_str(data, "press_id")
    planned_sheets = req_int(data, "planned_sheets", 1)
    start_utc = req_str(data, "start_utc")
    end_utc = req_str(data, "end_utc")
    start_dt = parse_dt(start_utc)
    end_dt = parse_dt(end_utc)
    if start_dt is None or end_dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "start_utc and end_utc must be ISO 8601 datetimes")

    job = db.jobs[job_id]
    press = db.presses[press_id]

    # Priority 6: job state
    if job["status"] not in ("PRESS_READY", "IN_PRODUCTION"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Press bookings require a PRESS_READY or IN_PRODUCTION job")

    # Priority 8: booking windows (past check, then half-open overlap)
    if start_dt < db.clock["dt"]:
        raise ApiError(ERR_WINDOW_IN_PAST, 409,
                       "Booking start_utc is earlier than the plant logical clock")
    for other in db.press_bookings.values():
        if other["press_id"] != press_id or other["status"] == "CANCELLED":
            continue
        other_start = parse_dt(other["start_utc"])
        other_end = parse_dt(other["end_utc"])
        # Half-open [start, end): conflict iff new.start < other.end and other.start < new.end
        if start_dt < other_end and other_start < end_dt:
            raise ApiError(ERR_PRESS_WINDOW_CONFLICT, 409,
                           "Window overlaps a non-CANCELLED booking on this press")

    # Priority 9: referenced-entity state
    if press["status"] != "ACTIVE":
        raise ApiError(ERR_PRESS_UNAVAILABLE, 409, "Press is DOWN")
    if press["press_type"] != job["route_type"]:
        raise ApiError(ERR_PRESS_TYPE_MISMATCH, 409,
                       "Press type %s contradicts job route %s"
                       % (press["press_type"], job["route_type"]))

    # Priority 10: capacity (sheet count, then sheet dims of the locked layout)
    if planned_sheets > press["max_sheets_per_booking"]:
        raise ApiError(ERR_SHEET_EXCEEDS_CAPACITY, 409,
                       "planned_sheets exceeds press max_sheets_per_booking")
    plan = locked_plan_for(job["id"])
    if plan is not None and (plan["sheet_w_cin"] > press["max_sheet_w_cin"]
                             or plan["sheet_h_cin"] > press["max_sheet_h_cin"]):
        raise ApiError(ERR_SHEET_EXCEEDS_CAPACITY, 409,
                       "Locked layout sheet dimensions exceed press maxima")

    rec = db.new_record()
    rec.update({
        "job_id": job_id,
        "press_id": press_id,
        "planned_sheets": planned_sheets,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "sheets_printed": None,
        "sheets_good": None,
        "status": "SCHEDULED",
    })
    db.press_bookings[rec["id"]] = rec
    return ok_object(ser_plain(rec), 201)


@bp.get("/plant/press-bookings")
def list_press_bookings():
    authenticate(ALL_ROLES)
    return list_response(
        db.press_bookings.values(),
        ser_plain,
        [("job_id", "job_id", "str"),
         ("press_id", "press_id", "str"),
         ("status", "status", "str")],
    )


@bp.get("/plant/press-bookings/<bookingId>")
def get_press_booking(bookingId):
    authenticate(ALL_ROLES)
    return ok_object(ser_plain(get_or_404(db.press_bookings, bookingId)))


@bp.post("/plant/press-bookings/<bookingId>/complete")
def complete_press_booking(bookingId):
    authenticate(("PressOperator",))
    rec = get_or_404(db.press_bookings, bookingId)
    data = get_body()
    sheets_printed = req_int(data, "sheets_printed", 0)
    sheets_good = req_int(data, "sheets_good", 0)
    if sheets_good > sheets_printed:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "sheets_good must not exceed sheets_printed")
    if rec["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a SCHEDULED booking can be completed")

    job = db.jobs[rec["job_id"]]
    stock = db.board_stocks.get(job["board_stock_id"]) if job["board_stock_id"] else None

    # Over-print: printed sheets beyond the job's remaining reservation must fit
    # the stock's unreserved available pool.
    excess = sheets_printed - job["reserved_sheets"]
    if excess > 0:
        if stock is None or available_sheets(stock) < excess:
            raise ApiError(ERR_INSUFFICIENT_BOARD_STOCK, 409,
                           "Over-print excess does not fit available board stock")

    release = min(sheets_printed, job["reserved_sheets"])

    # CASCADE L1: stock ledger settles
    if stock is not None:
        stock["consumed_sheets"] += sheets_printed
        stock["reserved_sheets"] -= release
        touch(stock)
    job["reserved_sheets"] -= release

    # CASCADE L2: job actuals accumulate
    job["sheets_consumed_actual"] += sheets_printed
    job["good_sheets_actual"] += sheets_good
    touch(job)

    rec["sheets_printed"] = sheets_printed
    rec["sheets_good"] = sheets_good
    rec["status"] = "COMPLETED"
    touch(rec)

    # CASCADE L3: LOCKED plan absorbs the realized picture
    plan = locked_plan_for(job["id"])
    if plan is not None:
        plan["realized_sheets_printed"] = job["sheets_consumed_actual"]
        plan["realized_good_sheets"] = job["good_sheets_actual"]
        consumed = job["sheets_consumed_actual"]
        if consumed > 0:
            plan["realized_waste_milli_pct"] = (
                (consumed - job["good_sheets_actual"]) * 100000 // consumed
            )
        else:
            plan["realized_waste_milli_pct"] = None
        touch(plan)

    return ok_object(ser_plain(rec))


@bp.post("/plant/press-bookings/<bookingId>/cancel")
def cancel_press_booking(bookingId):
    authenticate(("PressOperator",))
    rec = get_or_404(db.press_bookings, bookingId)
    if rec["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a SCHEDULED booking can be cancelled")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(ser_plain(rec))
