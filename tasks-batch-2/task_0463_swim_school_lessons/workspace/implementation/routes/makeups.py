"""MakeupCredit + MakeupBooking routes. PRD 3.8."""
from flask import Blueprint, request

from clock import clock
from db import store, iso, common_fields_on_create, touch
from errors import (
    err, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_STATE,
    ERR_CREDIT_EXPIRED, ERR_CREDIT_NOT_REDEEMABLE,
    ERR_MAKEUP_TIME_CONFLICT, ERR_MAKEUP_OCCURRENCE_FULL,
)
from helpers import (
    get_body, require_str, require_datetime, parse_pagination, paginate,
)
from middleware import get_principal, require_roles
from response import object_response, array_response
from domain import (
    serialize_makeup_credit, serialize_makeup_booking,
    reconcile_session_counts, credit_is_expired, effective_credit_status,
)
from lookups import (
    get_makeup_credit, get_class_session, get_makeup_booking, get_student,
)
from calculations import makeup_time_conflict

bp = Blueprint("makeups", __name__)

ALL_ROLES = ["SchoolAdmin", "BillingAdmin", "Instructor", "Parent"]


# ---------------------------------------------------------------------------
# MakeupCredit (read-only; issued automatically by side effects).
# ---------------------------------------------------------------------------
@bp.route("/makeup-credits", methods=["GET"])
def list_credits():
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.makeup_credits.values())
    for f in ("student_id", "origin_enrollment_id"):
        val = request.args.get(f)
        if val is not None:
            records = [r for r in records if r[f] == val]
    status_filter = request.args.get("status")
    if status_filter is not None:
        # Filter against the effective (clock-evaluated) status.
        records = [r for r in records if effective_credit_status(r) == status_filter]
    window, total = paginate(records, limit, offset)
    return array_response([serialize_makeup_credit(r) for r in window], limit, offset, total)


@bp.route("/makeup-credits/<id>", methods=["GET"])
def get_credit_route(id):
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    rec = get_makeup_credit(id)
    return object_response(serialize_makeup_credit(rec), 200)


# ---------------------------------------------------------------------------
# MakeupBooking — PRD 3.8.
# ---------------------------------------------------------------------------
@bp.route("/makeup-bookings", methods=["POST"])
def create_booking():
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "Parent"])
    body = get_body()
    makeup_credit_id = require_str(body, "makeup_credit_id")
    target_class_session_id = require_str(body, "target_class_session_id")
    occurrence_date = require_datetime(body, "occurrence_date")
    # Existence, body FKs left to right.
    credit = get_makeup_credit(makeup_credit_id)
    session = get_class_session(target_class_session_id)
    # priority 6: ownership for Parent — the credit's student belongs to the parent.
    student = store.students.get(credit["student_id"])
    if principal.role == "Parent":
        if student is None or principal.user_id != student["parent_id"]:
            err(ERR_NOT_RESOURCE_OWNER, "Parent may only redeem its own credit")
    # priority 11: credit validity — unexpired AND ISSUED.
    if credit_is_expired(credit):
        err(ERR_CREDIT_EXPIRED, "Makeup credit has expired")
    if credit["status"] != "ISSUED":
        err(ERR_CREDIT_NOT_REDEEMABLE, "Makeup credit is not redeemable")

    occ_start = session["start_minute"]
    occ_end = session["end_minute"]

    # priority 10: same-day overlap (half-open, no buffer) against the student's
    # BOOKED/ATTENDED bookings on the same occurrence_date.
    occ_iso = iso(occurrence_date)
    same_day = [
        b for b in store.makeup_bookings.values()
        if b["student_id"] == credit["student_id"]
        and b["status"] in ("BOOKED", "ATTENDED")
        and b["occurrence_date"] == occ_iso
    ]
    if makeup_time_conflict(occ_start, occ_end, same_day):
        err(ERR_MAKEUP_TIME_CONFLICT, "Overlapping makeup booking on this date")

    # priority 12: occurrence capacity — remaining = capacity - enrolled_count
    # - count(BOOKED bookings for the target session on that date).
    reconcile_session_counts(session)
    booked_on_date = sum(
        1 for b in store.makeup_bookings.values()
        if b["target_class_session_id"] == session["id"]
        and b["status"] == "BOOKED"
        and b["occurrence_date"] == occ_iso
    )
    remaining = session["capacity"] - session["enrolled_count"] - booked_on_date
    if remaining <= 0:
        err(ERR_MAKEUP_OCCURRENCE_FULL, "Target occurrence has no spare seat")

    rec = common_fields_on_create()
    rec.update({
        "makeup_credit_id": credit["id"],
        "student_id": credit["student_id"],
        "target_class_session_id": session["id"],
        "occurrence_date": occ_iso,
        "occurrence_start_minute": occ_start,
        "occurrence_end_minute": occ_end,
        "status": "BOOKED",
    })
    store.makeup_bookings[rec["id"]] = rec
    # Credit ISSUED -> REDEEMED.
    credit["status"] = "REDEEMED"
    touch(credit)
    return object_response(serialize_makeup_booking(rec), 201)


@bp.route("/makeup-bookings", methods=["GET"])
def list_bookings():
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.makeup_bookings.values())
    for f in ("makeup_credit_id", "student_id", "target_class_session_id", "status"):
        val = request.args.get(f)
        if val is not None:
            records = [r for r in records if r[f] == val]
    window, total = paginate(records, limit, offset)
    return array_response([serialize_makeup_booking(r) for r in window], limit, offset, total)


@bp.route("/makeup-bookings/<id>", methods=["GET"])
def get_booking_route(id):
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    rec = get_makeup_booking(id)
    return object_response(serialize_makeup_booking(rec), 200)


def _parent_owns_booking(principal, booking):
    if principal.role == "Parent":
        student = store.students.get(booking["student_id"])
        if student is None or principal.user_id != student["parent_id"]:
            err(ERR_NOT_RESOURCE_OWNER, "Parent may only act on its own booking")


def _instructor_teaches_target(principal, booking):
    if principal.role == "Instructor":
        session = store.class_sessions.get(booking["target_class_session_id"])
        if session is None or principal.user_id != session["instructor_id"]:
            err(ERR_NOT_RESOURCE_OWNER,
                "Instructor must teach the booking's target session")


@bp.route("/makeup-bookings/<id>/cancel", methods=["POST"])
def cancel_booking(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "Parent"])
    booking = get_makeup_booking(id)
    _parent_owns_booking(principal, booking)
    # State legality: only a BOOKED booking may be cancelled.
    if booking["status"] != "BOOKED":
        err(ERR_INVALID_STATE, "Only a BOOKED booking may be cancelled")
    credit = store.makeup_credits.get(booking["makeup_credit_id"])
    # PRD 3.8: an already-expired credit cannot be restored even on cancel.
    if credit is not None and credit_is_expired(credit):
        err(ERR_CREDIT_EXPIRED, "Cannot restore an expired credit")
    booking["status"] = "CANCELLED"
    touch(booking)
    if credit is not None:
        # Restore credit REDEEMED -> ISSUED (conservation, no drift).
        credit["status"] = "ISSUED"
        touch(credit)
    return object_response(serialize_makeup_booking(booking), 200)


@bp.route("/makeup-bookings/<id>/mark-attended", methods=["POST"])
def mark_attended(id):
    principal = get_principal()
    require_roles(principal, ["Instructor"])
    booking = get_makeup_booking(id)
    _instructor_teaches_target(principal, booking)
    if booking["status"] != "BOOKED":
        err(ERR_INVALID_STATE, "Only a BOOKED booking may be marked attended")
    booking["status"] = "ATTENDED"
    touch(booking)
    # Credit redemption is final — remains REDEEMED, never restored.
    return object_response(serialize_makeup_booking(booking), 200)


@bp.route("/makeup-bookings/<id>/mark-no-show", methods=["POST"])
def mark_no_show(id):
    principal = get_principal()
    require_roles(principal, ["Instructor"])
    booking = get_makeup_booking(id)
    _instructor_teaches_target(principal, booking)
    if booking["status"] != "BOOKED":
        err(ERR_INVALID_STATE, "Only a BOOKED booking may be marked no-show")
    booking["status"] = "NO_SHOW"
    touch(booking)
    # Credit redemption is final — the makeup chance is consumed.
    return object_response(serialize_makeup_booking(booking), 200)
