"""Booking endpoints: create, list, get, cancel, reschedule, attendance."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import core

bp = Blueprint("bookings", __name__)

BOOKING_ROLES = {"SchoolAdmin", "FrontOfficeStaff", "FamilyGuardian"}
BOOKING_READERS = {"SchoolAdmin", "FrontOfficeStaff", "Teacher", "FamilyGuardian"}
ATTENDANCE_ROLES = {"SchoolAdmin", "FrontOfficeStaff", "Teacher"}


def _check_booking_read_scope(role, uid, booking):
    if role == "Teacher" and booking["teacher_id"] != uid:
        raise errors.forbidden("Teacher may view only their own bookings")
    if role == "FamilyGuardian" and booking["family_id"] != uid:
        raise errors.forbidden("FamilyGuardian may view only their own family's bookings")


@bp.route("/conf/bookings", methods=["POST"])
def create_booking():
    role, uid = middleware.get_auth()
    middleware.require_roles(role, BOOKING_ROLES)
    body = util.get_body()
    util.require_fields(body, ["slot_id", "student_id", "channel"])
    slot_id = body["slot_id"]
    student_id = body["student_id"]
    if not isinstance(slot_id, str) or not isinstance(student_id, str):
        raise errors.validation("slot_id and student_id must be strings")
    channel = util.require_enum(body, "channel", {"IN_PERSON", "VIRTUAL"})
    interpreter_language = util.optional_string(body, "interpreter_language", default=None)

    slot = core.get_slot_or_404(slot_id)
    student = core.get_student_or_404(student_id)
    window = core.get_window_or_404(slot["window_id"])
    teacher = core.get_teacher_or_404(slot["teacher_id"])
    family = core.get_family_or_404(student["family_id"])

    # Ownership (p3)
    middleware.check_family_owns(role, uid, family["id"])

    # Window state (p7)
    if window["status"] != "BOOKING_OPEN":
        raise errors.invalid_window_state("booking requires BOOKING_OPEN")

    # Family restriction (p8 entity-state tier) — staff bypass
    if role == "FamilyGuardian" and family["status"] != "ACTIVE":
        raise errors.family_restricted()

    # Full booking validation battery
    core.validate_booking(window, slot, student, channel, family, teacher)

    booked_by_role = "FAMILY_SELF" if role == "FamilyGuardian" else "FRONT_OFFICE"
    booking = core.create_booking(window, slot, student, channel, booked_by_role,
                                  interpreter_language)
    return response.success_object(serializers.booking_view(booking), status=201)


@bp.route("/conf/bookings", methods=["GET"])
def list_bookings():
    role, uid = middleware.get_auth()
    middleware.require_roles(role, BOOKING_READERS)
    limit, offset = util.parse_pagination(request.args)
    filters = {
        "window_id": request.args.get("window_id"),
        "family_id": request.args.get("family_id"),
        "student_id": request.args.get("student_id"),
        "teacher_id": request.args.get("teacher_id"),
        "slot_id": request.args.get("slot_id"),
        "rescheduled_from_booking_id": request.args.get("rescheduled_from_booking_id"),
        "status": request.args.get("status"),
    }
    items = list(db.bookings.values())
    if role == "Teacher":
        items = [b for b in items if b["teacher_id"] == uid]
    if role == "FamilyGuardian":
        items = [b for b in items if b["family_id"] == uid]
    for key, value in filters.items():
        if value is not None:
            items = [b for b in items if b.get(key) == value]
    items.sort(key=lambda b: b["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.booking_view(b) for b in page],
                                 total, limit, offset)


@bp.route("/conf/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, BOOKING_READERS)
    booking = core.get_booking_or_404(bid)
    _check_booking_read_scope(role, uid, booking)
    return response.success_object(serializers.booking_view(booking))


@bp.route("/conf/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, BOOKING_ROLES)
    util.get_body()  # optional free-text reason
    booking = core.get_booking_or_404(bid)
    window = core.get_window_or_404(booking["window_id"])
    slot = core.get_slot_or_404(booking["slot_id"])

    # Ownership (p3)
    middleware.check_family_owns(role, uid, booking["family_id"])

    # Window state (p7)
    if window["status"] != "BOOKING_OPEN":
        raise errors.invalid_window_state("cancel requires BOOKING_OPEN")

    # Entity state (p8)
    if booking["status"] != "CONFIRMED":
        raise errors.invalid_state("only a CONFIRMED booking can be cancelled")

    # Temporal cutoff (p10) — staff bypass
    if role == "FamilyGuardian":
        cutoff = util.parse_dt(slot["start_at"]) - timedelta(hours=window["cancel_cutoff_hours"])
        if util.clock_dt() > cutoff:
            raise errors.cancellation_cutoff()

    booking["status"] = "CANCELLED"
    booking["cancel_reason"] = "FAMILY_REQUEST" if role == "FamilyGuardian" else "STAFF_REQUEST"
    booking["version"] += 1
    booking["updated_at"] = util.now_iso()
    if slot["status"] == "BOOKED":
        core.open_slot_with_promotion(slot)
    core.cancel_open_requests_for_booking(booking)
    return response.success_object(serializers.booking_view(booking))


@bp.route("/conf/bookings/<bid>/reschedule", methods=["POST"])
def reschedule_booking(bid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, BOOKING_ROLES)
    body = util.get_body()
    util.require_fields(body, ["new_slot_id"])
    new_slot_id = body["new_slot_id"]
    if not isinstance(new_slot_id, str):
        raise errors.validation("new_slot_id must be a string")
    booking = core.get_booking_or_404(bid)
    new_slot = core.get_slot_or_404(new_slot_id)
    window = core.get_window_or_404(booking["window_id"])
    old_slot = core.get_slot_or_404(booking["slot_id"])

    # Ownership (p3)
    middleware.check_family_owns(role, uid, booking["family_id"])

    # OCC (p6)
    expected = body.get("expected_booking_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise errors.validation("expected_booking_version must be an integer")
        if expected != booking["version"]:
            raise errors.stale_version()

    is_staff = middleware.is_staff(role)

    # Window state (p7): family needs BOOKING_OPEN; staff may also use IN_PROGRESS
    if is_staff:
        if booking["status"] == "CONFIRMED":
            allowed_states = ("BOOKING_OPEN", "IN_PROGRESS")
        elif booking["status"] == "NO_SHOW":
            allowed_states = ("IN_PROGRESS", "COMPLETED")
        else:
            allowed_states = ()
    else:
        allowed_states = ("BOOKING_OPEN",)
    if window["status"] not in allowed_states:
        raise errors.invalid_window_state("window status does not allow reschedule")

    # Entity state (p8)
    if is_staff:
        if booking["status"] not in ("CONFIRMED", "NO_SHOW"):
            raise errors.invalid_state("only CONFIRMED or NO_SHOW bookings can be rescheduled")
    else:
        if booking["status"] != "CONFIRMED":
            raise errors.invalid_state("only a CONFIRMED booking can be rescheduled")
        if role == "FamilyGuardian":
            family = core.get_family_or_404(booking["family_id"])
            if family["status"] != "ACTIVE":
                raise errors.family_restricted()

    # Temporal (p10): family cutoff vs old slot; NO_SHOW reschedule needs future slot
    if role == "FamilyGuardian":
        cutoff = util.parse_dt(old_slot["start_at"]) - timedelta(hours=window["cancel_cutoff_hours"])
        if util.clock_dt() > cutoff:
            raise errors.cancellation_cutoff()
    if booking["status"] == "NO_SHOW":
        if util.parse_dt(new_slot["start_at"]) <= util.clock_dt():
            raise errors.invalid_state("new slot must start after the current time")

    # New slot must be in the same window
    if new_slot["window_id"] != booking["window_id"]:
        raise errors.validation("new_slot_id must belong to the same window")

    # Full booking validation battery against the new slot
    student = core.get_student_or_404(booking["student_id"])
    family = core.get_family_or_404(booking["family_id"])
    teacher = core.get_teacher_or_404(new_slot["teacher_id"])
    channel = util.optional_enum(body, "channel", {"IN_PERSON", "VIRTUAL"},
                                 default=booking["channel"])
    core.validate_booking(window, new_slot, student, channel, family, teacher,
                          exclude_booking_id=booking["id"])

    # --- Commit: old booking -> RESCHEDULED; successor created ---
    old_language = booking["interpreter_language"]
    booked_by_role = booking["booked_by_role"]
    booking["status"] = "RESCHEDULED"
    booking["cancel_reason"] = "RESCHEDULED"
    booking["version"] += 1
    booking["updated_at"] = util.now_iso()
    if old_slot["status"] == "BOOKED":
        core.open_slot_with_promotion(old_slot)
    core.cancel_open_requests_for_booking(booking)

    successor = core.create_booking(window, new_slot, student, channel, booked_by_role,
                                    old_language,
                                    rescheduled_from_booking_id=booking["id"])
    return response.success_object(serializers.booking_view(successor))


@bp.route("/conf/bookings/<bid>/attendance", methods=["POST"])
def mark_attendance(bid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, ATTENDANCE_ROLES)
    body = util.get_body()
    util.require_fields(body, ["outcome"])
    outcome = util.require_enum(body, "outcome", {"ATTENDED", "LATE", "NO_SHOW", "EXCUSED"})
    note = util.optional_string(body, "note", default=None)

    booking = core.get_booking_or_404(bid)
    window = core.get_window_or_404(booking["window_id"])
    slot = core.get_slot_or_404(booking["slot_id"])

    # Ownership (p3)
    middleware.check_teacher_owns(role, uid, booking["teacher_id"])

    # Window state (p7)
    if window["status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise errors.invalid_window_state("attendance requires IN_PROGRESS or COMPLETED")

    # Entity state (p8)
    if booking["status"] != "CONFIRMED":
        raise errors.invalid_state("only a CONFIRMED booking can be marked")
    if util.clock_dt() < util.parse_dt(slot["start_at"]):
        raise errors.invalid_state("attendance cannot be marked before the slot starts")

    if outcome in ("ATTENDED", "LATE"):
        booking["status"] = "COMPLETED"
        booking["version"] += 1
        booking["updated_at"] = util.now_iso()
        core.record_attendance(booking, outcome, role, uid, note)
    elif outcome == "EXCUSED":
        booking["status"] = "EXCUSED"
        booking["version"] += 1
        booking["updated_at"] = util.now_iso()
        core.record_attendance(booking, outcome, role, uid, note)
    else:  # NO_SHOW
        core.mark_no_show(booking, role, uid, note)

    return response.success_object(serializers.booking_view(booking))
