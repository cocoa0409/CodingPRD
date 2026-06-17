"""Booking routes: create (OCC), confirm, dispatch, cancel, no-show."""

from flask import Blueprint, request

import errors
from db import db, new_common, public, sorted_by_created, touch
from errors import err
from middleware import (as_int, as_number, as_str, get_body, get_user_context,
                        parse_pagination, require_fields, require_role)
from response import list_success, success
from services import cascade, ledger
from services.calc import (INSTRUCTOR_BUFFER_MINUTES, NO_SHOW_SUSPEND_THRESHOLD,
                           booking_cost_estimate)
from services.common import (fk_or_404, find_or_404, half_open_overlap, parse_dt,
                             windows_within_buffer)

bp = Blueprint("bookings", __name__)


@bp.post("/flight-school/bookings")
def create_booking():
    _, role = get_user_context()
    require_role(role, {"Student", "Dispatcher"})
    body = get_body()
    require_fields(body, ["enrollment_id", "aircraft_id", "lesson_type",
                          "start_at", "end_at", "estimated_hours",
                          "expected_aircraft_version"])
    enrollment_id = as_str(body, "enrollment_id")
    aircraft_id = as_str(body, "aircraft_id")
    lesson_type = body["lesson_type"]
    if lesson_type not in ("DUAL", "SOLO"):
        raise err(errors.ERR_INVALID_REQUEST, "lesson_type must be DUAL or SOLO.")
    instructor_id = body.get("instructor_id")
    estimated_hours = as_number(body, "estimated_hours")
    if estimated_hours <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "estimated_hours must be > 0.")
    expected_version = as_int(body, "expected_aircraft_version")
    start_at = parse_dt(body["start_at"])
    end_at = parse_dt(body["end_at"])
    if lesson_type == "DUAL" and instructor_id is None:
        raise err(errors.ERR_INVALID_REQUEST, "DUAL lesson requires instructor_id.")

    # Existence (priority 3), left-to-right: enrollment, aircraft, instructor.
    enrollment = fk_or_404(db.enrollments, enrollment_id)
    aircraft = fk_or_404(db.aircraft, aircraft_id)
    if instructor_id is not None:
        fk_or_404(db.instructors, instructor_id)

    # OCC (priority 5): runs after existence + request-shape, before business.
    if expected_version != aircraft["version"]:
        raise err(errors.ERR_STALE_AIRCRAFT_VERSION,
                  "expected_aircraft_version does not match aircraft version.")

    # Compute estimate using the referenced aircraft + (DUAL) instructor.
    instructor = db.instructors.get(instructor_id) if instructor_id else None
    cfi_rate = instructor["cfi_rate_cents_per_hour"] if instructor else 0
    estimated_cost = booking_cost_estimate(
        aircraft["rental_rate_cents_per_hour"], cfi_rate,
        estimated_hours, aircraft["is_complex"], lesson_type)

    record = new_common()
    record.update({
        "enrollment_id": enrollment_id,
        "aircraft_id": aircraft_id,
        "instructor_id": instructor_id,
        "lesson_type": lesson_type,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "estimated_hours": estimated_hours,
        "estimated_cost_cents": estimated_cost,
        "status": "REQUESTED",
    })
    db.bookings[record["id"]] = record

    # The successful create claims a schedule slice: advance aircraft.version.
    touch(aircraft)

    return success(public(record), status=201)


@bp.get("/flight-school/bookings")
def list_bookings():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor"})
    limit, offset = parse_pagination()
    items = list(db.bookings.values())
    for field in ("enrollment_id", "aircraft_id", "instructor_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [b for b in items if b.get(field) == val]
    items = sorted_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([public(b) for b in page], limit, offset, total)


@bp.get("/flight-school/bookings/<booking_id>")
def get_booking(booking_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor"})
    record = find_or_404(db.bookings, booking_id)
    return success(public(record))


def _aircraft_time_conflict(booking):
    """True if booking's window overlaps another live booking on the aircraft."""
    a_start = parse_dt(booking["start_at"])
    a_end = parse_dt(booking["end_at"])
    for other in db.bookings.values():
        if other["id"] == booking["id"]:
            continue
        if other["aircraft_id"] != booking["aircraft_id"]:
            continue
        if other["status"] not in ("REQUESTED", "CONFIRMED", "DISPATCHED"):
            continue
        if half_open_overlap(a_start, a_end,
                             parse_dt(other["start_at"]), parse_dt(other["end_at"])):
            return True
    return False


def _instructor_time_conflict(booking):
    """True if the instructor has a booking within the buffer of this window."""
    instructor_id = booking["instructor_id"]
    if instructor_id is None:
        return False
    a_start = parse_dt(booking["start_at"])
    a_end = parse_dt(booking["end_at"])
    for other in db.bookings.values():
        if other["id"] == booking["id"]:
            continue
        if other.get("instructor_id") != instructor_id:
            continue
        if other["status"] not in ("REQUESTED", "CONFIRMED", "DISPATCHED"):
            continue
        if windows_within_buffer(parse_dt(other["start_at"]), parse_dt(other["end_at"]),
                                 a_start, a_end, INSTRUCTOR_BUFFER_MINUTES):
            return True
    return False


@bp.post("/flight-school/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    _, role = get_user_context()
    require_role(role, {"Dispatcher"})
    booking = find_or_404(db.bookings, booking_id)
    # State.
    if booking["status"] != "REQUESTED":
        raise err(errors.ERR_BOOKING_NOT_REQUESTED, "Booking is not REQUESTED.")
    aircraft = db.aircraft[booking["aircraft_id"]]
    # Safety: aircraft must be AVAILABLE.
    if aircraft["status"] != "AVAILABLE":
        raise err(errors.ERR_AIRCRAFT_GROUNDED, "Aircraft is not AVAILABLE.")
    # Temporal: aircraft overlap.
    if _aircraft_time_conflict(booking):
        raise err(errors.ERR_AIRCRAFT_TIME_CONFLICT, "Aircraft time conflict.")
    # Temporal: instructor buffer (DUAL only).
    if booking["lesson_type"] == "DUAL" and _instructor_time_conflict(booking):
        raise err(errors.ERR_INSTRUCTOR_TIME_CONFLICT, "Instructor time conflict.")
    # Fiscal: deposit balance >= estimated_cost_cents.
    enrollment = db.enrollments[booking["enrollment_id"]]
    student = db.students[enrollment["student_id"]]
    if student["deposit_balance_cents"] < booking["estimated_cost_cents"]:
        raise err(errors.ERR_INSUFFICIENT_DEPOSIT, "Insufficient deposit for confirm.")

    booking["status"] = "CONFIRMED"
    touch(booking)
    ledger.hold(student, booking["estimated_cost_cents"], booking["id"])
    return success(public(booking))


@bp.post("/flight-school/bookings/<booking_id>/dispatch")
def dispatch_booking(booking_id):
    _, role = get_user_context()
    require_role(role, {"Dispatcher"})
    booking = find_or_404(db.bookings, booking_id)
    if booking["status"] != "CONFIRMED":
        raise err(errors.ERR_BOOKING_NOT_CONFIRMED, "Booking is not CONFIRMED.")
    aircraft = db.aircraft[booking["aircraft_id"]]
    if aircraft["status"] != "AVAILABLE":
        raise err(errors.ERR_AIRCRAFT_GROUNDED, "Aircraft is not AVAILABLE.")
    enrollment = db.enrollments[booking["enrollment_id"]]
    if enrollment["status"] != "ACTIVE":
        raise err(errors.ERR_ENROLLMENT_NOT_ACTIVE, "Enrollment is not ACTIVE.")
    if enrollment["medical_status"] != "CLEARED":
        raise err(errors.ERR_MEDICAL_NOT_CLEARED, "Medical not CLEARED.")
    if booking["lesson_type"] == "SOLO":
        has_solo = any(
            e["enrollment_id"] == enrollment["id"]
            and e["endorsement_code"] == "SOLO"
            and e["status"] == "VALID"
            for e in db.endorsements.values()
        )
        if not has_solo:
            raise err(errors.ERR_SOLO_ENDORSEMENT_MISSING,
                      "No VALID SOLO endorsement for the enrollment.")
    booking["status"] = "DISPATCHED"
    touch(booking)
    return success(public(booking))


@bp.post("/flight-school/bookings/<booking_id>/cancel")
def cancel_booking_endpoint(booking_id):
    _, role = get_user_context()
    require_role(role, {"Student", "Dispatcher"})
    booking = find_or_404(db.bookings, booking_id)
    if booking["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err(errors.ERR_BOOKING_NOT_CANCELLABLE, "Booking is not cancellable.")
    was_confirmed = booking["status"] == "CONFIRMED"
    booking["status"] = "CANCELLED"
    touch(booking)
    if was_confirmed:
        enrollment = db.enrollments[booking["enrollment_id"]]
        student = db.students[enrollment["student_id"]]
        ledger.release(student, booking["estimated_cost_cents"], booking["id"])
    return success(public(booking))


@bp.post("/flight-school/bookings/<booking_id>/no-show")
def no_show_booking(booking_id):
    _, role = get_user_context()
    require_role(role, {"Dispatcher"})
    booking = find_or_404(db.bookings, booking_id)
    if booking["status"] != "CONFIRMED":
        raise err(errors.ERR_BOOKING_NOT_CONFIRMED, "Booking is not CONFIRMED.")
    booking["status"] = "NO_SHOW"
    touch(booking)
    enrollment = db.enrollments[booking["enrollment_id"]]
    student = db.students[enrollment["student_id"]]
    # Release the held estimate back to balance.
    ledger.release(student, booking["estimated_cost_cents"], booking["id"])
    # Increment strikes.
    student["no_show_strikes"] += 1
    touch(student)
    cascade.refresh_student_status(student)
    # Cascade enrollment suspension if threshold reached and enrollment ACTIVE.
    cascade.apply_no_show_strike_cascade(student, enrollment)
    return success(public(booking))
