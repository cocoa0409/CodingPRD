"""Flight log routes: create draft, list, get, post (settle), void."""

from flask import Blueprint, request

import errors
from db import db, new_common, public, sorted_by_created, touch
from errors import err
from middleware import (as_int, as_number, as_str, get_body, get_user_context,
                        parse_pagination, require_fields, require_role)
from response import list_success, success
from services import ledger
from services.calc import flight_charge
from services.common import fk_or_404, find_or_404

bp = Blueprint("flight_logs", __name__)


@bp.post("/flight-school/flight-logs")
def create_flight_log():
    _, role = get_user_context()
    require_role(role, {"Instructor", "Dispatcher"})
    body = get_body()
    require_fields(body, ["booking_id", "hobbs_start", "hobbs_end",
                          "tach_start", "tach_end", "landings"])
    booking_id = as_str(body, "booking_id")
    hobbs_start = as_number(body, "hobbs_start")
    hobbs_end = as_number(body, "hobbs_end")
    tach_start = as_number(body, "tach_start")
    tach_end = as_number(body, "tach_end")
    landings = as_int(body, "landings")
    if landings < 1:
        raise err(errors.ERR_INVALID_REQUEST, "landings must be >= 1.")

    booking = fk_or_404(db.bookings, booking_id)

    record = new_common()
    record.update({
        "booking_id": booking_id,
        "enrollment_id": booking["enrollment_id"],
        "aircraft_id": booking["aircraft_id"],
        "instructor_id": booking.get("instructor_id"),
        "hobbs_start": hobbs_start,
        "hobbs_end": hobbs_end,
        "tach_start": tach_start,
        "tach_end": tach_end,
        "landings": landings,
        "billed_hours": None,
        "aircraft_charge_cents": None,
        "instructor_charge_cents": 0,
        "total_charge_cents": None,
        "status": "DRAFT",
    })
    db.flight_logs[record["id"]] = record
    return success(public(record), status=201)


@bp.get("/flight-school/flight-logs")
def list_flight_logs():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor"})
    limit, offset = parse_pagination()
    items = list(db.flight_logs.values())
    for field in ("booking_id", "enrollment_id", "aircraft_id", "instructor_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [f for f in items if f.get(field) == val]
    items = sorted_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([public(f) for f in page], limit, offset, total)


@bp.get("/flight-school/flight-logs/<flight_log_id>")
def get_flight_log(flight_log_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor"})
    record = find_or_404(db.flight_logs, flight_log_id)
    return success(public(record))


@bp.post("/flight-school/flight-logs/<flight_log_id>/post")
def post_flight_log(flight_log_id):
    _, role = get_user_context()
    require_role(role, {"Instructor", "Dispatcher"})
    log = find_or_404(db.flight_logs, flight_log_id)
    # State.
    if log["status"] != "DRAFT":
        raise err(errors.ERR_FLIGHT_LOG_NOT_DRAFT, "Flight log is not DRAFT.")
    booking = db.bookings[log["booking_id"]]
    if booking["status"] != "DISPATCHED":
        raise err(errors.ERR_BOOKING_NOT_DISPATCHED, "Booking is not DISPATCHED.")
    aircraft = db.aircraft[log["aircraft_id"]]
    # Meter sanity (400).
    if not (log["hobbs_end"] > log["hobbs_start"] and log["tach_end"] > log["tach_start"]):
        raise err(errors.ERR_INVALID_METER_READING, "Invalid meter reading.")
    # Continuity (409) — compare to current live meters.
    if log["hobbs_start"] != aircraft["current_hobbs"] or log["tach_start"] != aircraft["current_tach"]:
        raise err(errors.ERR_METER_DISCONTINUITY, "Meter discontinuity.")

    # Compute the flight charge.
    instructor = db.instructors.get(log.get("instructor_id"))
    cfi_rate = instructor["cfi_rate_cents_per_hour"] if instructor else 0
    billed_hours, aircraft_charge, instructor_charge, total = flight_charge(
        aircraft["billing_basis"], log["hobbs_start"], log["hobbs_end"],
        log["tach_start"], log["tach_end"],
        aircraft["rental_rate_cents_per_hour"], cfi_rate, booking["lesson_type"])

    # Fiscal: balance + held estimate >= total_charge_cents.
    enrollment = db.enrollments[log["enrollment_id"]]
    student = db.students[enrollment["student_id"]]
    estimate = booking["estimated_cost_cents"]
    if student["deposit_balance_cents"] + estimate < total:
        raise err(errors.ERR_INSUFFICIENT_DEPOSIT, "Insufficient deposit for post.")

    # --- Atomic finalization ---
    log["billed_hours"] = billed_hours
    log["aircraft_charge_cents"] = aircraft_charge
    log["instructor_charge_cents"] = instructor_charge
    log["total_charge_cents"] = total
    log["status"] = "POSTED"
    touch(log)

    # Deposit settlement (final): RELEASE estimate, CONSUME actual.
    ledger.release(student, estimate, booking["id"])
    ledger.consume(student, total, booking["id"], log["id"])

    # Advance aircraft meters (bumps aircraft version).
    aircraft["current_hobbs"] = log["hobbs_end"]
    aircraft["current_tach"] = log["tach_end"]
    touch(aircraft)

    # Roll up enrollment hours per lesson_type.
    if booking["lesson_type"] == "DUAL":
        enrollment["logged_dual_hours"] = round(enrollment["logged_dual_hours"] + billed_hours, 1)
    else:
        enrollment["logged_solo_hours"] = round(enrollment["logged_solo_hours"] + billed_hours, 1)
    touch(enrollment)

    # Cascade booking DISPATCHED -> COMPLETED.
    booking["status"] = "COMPLETED"
    touch(booking)

    return success(public(log))


@bp.post("/flight-school/flight-logs/<flight_log_id>/void")
def void_flight_log(flight_log_id):
    _, role = get_user_context()
    require_role(role, {"Dispatcher"})
    log = find_or_404(db.flight_logs, flight_log_id)
    if log["status"] != "DRAFT":
        raise err(errors.ERR_FLIGHT_LOG_NOT_DRAFT, "Flight log is not DRAFT.")
    log["status"] = "VOID"
    touch(log)
    return success(public(log))
