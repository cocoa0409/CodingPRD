from flask import Blueprint, request
from datetime import timedelta
import db
from errors import raise_error, ERR_BOOKING_NOT_FOUND, ERR_BAD_REQUEST, ERR_VERSION_CONFLICT, \
    ERR_ROOM_NOT_FOUND, ERR_ROOM_NOT_ACTIVE, ERR_INVALID_BOOKING_STATE, ERR_TIME_CONFLICT, \
    ERR_CAPACITY_EXCEEDED, ERR_INVALID_TIME_RANGE, ERR_BOOKING_TOO_SHORT, ERR_BOOKING_TOO_LONG, \
    ERR_BOOKING_IN_PAST, ERR_CHECKIN_WINDOW
from middleware import require_roles, get_auth
from response import success_response, list_response
from services.audit import create_audit_log
from services.cost import compute_cost_cents
from services.overlap import has_overlap, parse_dt
from services.waitlist_service import promote_waitlist

bookings_bp = Blueprint("bookings", __name__)


def booking_to_dict(b):
    return dict(b)


def _validate_booking_times(start_time_str, end_time_str):
    """Validate and parse booking time range. Returns (start_dt, end_dt)."""
    try:
        start_dt = parse_dt(start_time_str)
        end_dt = parse_dt(end_time_str)
    except (ValueError, TypeError):
        raise_error(ERR_BAD_REQUEST, "Invalid datetime format")

    if end_dt <= start_dt:
        raise_error(ERR_INVALID_TIME_RANGE, "end_time must be after start_time")

    duration = end_dt - start_dt
    if duration < timedelta(minutes=15):
        raise_error(ERR_BOOKING_TOO_SHORT, "Booking must be at least 15 minutes")
    if duration > timedelta(hours=8):
        raise_error(ERR_BOOKING_TOO_LONG, "Booking must not exceed 8 hours")

    now = db.utc_now()
    if start_dt <= now:
        raise_error(ERR_BOOKING_IN_PAST, "Booking start_time must be in the future")

    return start_dt, end_dt


@bookings_bp.route("/bookings", methods=["POST"])
def create_booking():
    user_id, role = get_auth()
    data = request.get_json(force=True, silent=True)
    if not data:
        raise_error(ERR_BAD_REQUEST, "Request body is required")

    for field in ("room_id", "title", "start_time", "end_time", "attendee_count"):
        if field not in data or data[field] is None:
            raise_error(ERR_BAD_REQUEST, f"Missing required field: {field}")

    room_id = data["room_id"]
    room = db.rooms.get(room_id)
    if not room:
        raise_error(ERR_ROOM_NOT_FOUND, "Room not found")

    if room["status"] != "ACTIVE":
        raise_error(ERR_ROOM_NOT_ACTIVE, "Room is not ACTIVE")

    start_dt, end_dt = _validate_booking_times(data["start_time"], data["end_time"])

    attendee_count = data["attendee_count"]
    if not isinstance(attendee_count, int) or attendee_count < 1:
        raise_error(ERR_BAD_REQUEST, "attendee_count must be a positive integer")
    if attendee_count > room["capacity"]:
        raise_error(ERR_CAPACITY_EXCEEDED, "Attendee count exceeds room capacity")

    # For STANDARD rooms, check conflict now
    if room["tier"] == "STANDARD":
        if has_overlap(room_id, start_dt, end_dt):
            raise_error(ERR_TIME_CONFLICT, "Time slot overlaps with an existing booking")

    now = db.now_iso()
    booking_id = db.gen_id()
    booking = {
        "id": booking_id,
        "room_id": room_id,
        "organizer_id": user_id,
        "title": data["title"],
        "start_time": data["start_time"],
        "end_time": data["end_time"],
        "attendee_count": attendee_count,
        "status": "TENTATIVE",
        "series_id": None,
        "cost_cents": None,
        "rejection_reason": None,
        "checked_in_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.bookings[booking_id] = booking

    create_audit_log(user_id, role, "booking.created", "Booking", booking_id,
                     {"after": dict(booking)})

    # Auto-transition based on tier
    if room["tier"] == "STANDARD":
        cost = compute_cost_cents(room, start_dt, end_dt)
        booking["status"] = "CONFIRMED"
        booking["cost_cents"] = cost
        booking["updated_at"] = db.now_iso()
        booking["version"] += 1
        create_audit_log(user_id, role, "booking.confirmed", "Booking", booking_id,
                         {"before": {"status": "TENTATIVE"},
                          "after": {"status": "CONFIRMED", "cost_cents": cost}})
    else:
        booking["status"] = "PENDING_APPROVAL"
        booking["updated_at"] = db.now_iso()
        booking["version"] += 1
        create_audit_log(user_id, role, "booking.pending_approval", "Booking", booking_id,
                         {"before": {"status": "TENTATIVE"},
                          "after": {"status": "PENDING_APPROVAL"}})

    return success_response(booking_to_dict(booking), 201)


@bookings_bp.route("/bookings", methods=["GET"])
def list_bookings():
    get_auth()
    args = request.args

    filtered = list(db.bookings.values())

    if "room_id" in args:
        filtered = [b for b in filtered if b["room_id"] == args["room_id"]]
    if "organizer_id" in args:
        filtered = [b for b in filtered if b["organizer_id"] == args["organizer_id"]]
    if "status" in args:
        filtered = [b for b in filtered if b["status"] == args["status"]]
    if "start_after" in args:
        try:
            sa = parse_dt(args["start_after"])
            filtered = [b for b in filtered if parse_dt(b["start_time"]) > sa]
        except (ValueError, TypeError):
            pass
    if "start_before" in args:
        try:
            sb = parse_dt(args["start_before"])
            filtered = [b for b in filtered if parse_dt(b["start_time"]) < sb]
        except (ValueError, TypeError):
            pass

    filtered.sort(key=lambda x: x["created_at"])
    total_count = len(filtered)

    limit = min(max(int(args.get("limit", 20)), 1), 100)
    offset = max(int(args.get("offset", 0)), 0)

    page = filtered[offset:offset + limit]
    return list_response([booking_to_dict(b) for b in page], total_count, limit, offset)


@bookings_bp.route("/bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    get_auth()
    booking = db.bookings.get(booking_id)
    if not booking:
        raise_error(ERR_BOOKING_NOT_FOUND, "Booking not found")
    return success_response(booking_to_dict(booking))


@bookings_bp.route("/bookings/<booking_id>/approve", methods=["POST"])
def approve_booking(booking_id):
    user_id, role = require_roles("manager", "facility_admin")
    booking = db.bookings.get(booking_id)
    if not booking:
        raise_error(ERR_BOOKING_NOT_FOUND, "Booking not found")

    # Version check
    data = request.get_json(force=True, silent=True) or {}
    if "version" in data and data["version"] is not None:
        if data["version"] != booking["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")

    if booking["status"] != "PENDING_APPROVAL":
        raise_error(ERR_INVALID_BOOKING_STATE, "Booking is not PENDING_APPROVAL")

    room = db.rooms.get(booking["room_id"])
    if not room or room["status"] != "ACTIVE":
        raise_error(ERR_ROOM_NOT_ACTIVE, "Room is not ACTIVE")

    # Overlap check at approval time
    if has_overlap(booking["room_id"], booking["start_time"], booking["end_time"],
                   exclude_booking_id=booking_id):
        raise_error(ERR_TIME_CONFLICT, "Time slot overlaps with an existing booking")

    start_dt = parse_dt(booking["start_time"])
    end_dt = parse_dt(booking["end_time"])
    cost = compute_cost_cents(room, start_dt, end_dt)

    old_status = booking["status"]
    booking["status"] = "CONFIRMED"
    booking["cost_cents"] = cost
    booking["updated_at"] = db.now_iso()
    booking["version"] += 1

    create_audit_log(user_id, role, "booking.approved", "Booking", booking_id,
                     {"before": {"status": old_status},
                      "after": {"status": "CONFIRMED", "cost_cents": cost}})

    return success_response(booking_to_dict(booking))


@bookings_bp.route("/bookings/<booking_id>/reject", methods=["POST"])
def reject_booking(booking_id):
    user_id, role = require_roles("manager", "facility_admin")
    booking = db.bookings.get(booking_id)
    if not booking:
        raise_error(ERR_BOOKING_NOT_FOUND, "Booking not found")

    data = request.get_json(force=True, silent=True) or {}
    if "version" in data and data["version"] is not None:
        if data["version"] != booking["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")

    if booking["status"] != "PENDING_APPROVAL":
        raise_error(ERR_INVALID_BOOKING_STATE, "Booking is not PENDING_APPROVAL")

    if "rejection_reason" not in data or not data["rejection_reason"]:
        raise_error(ERR_BAD_REQUEST, "rejection_reason is required")

    old_status = booking["status"]
    booking["status"] = "CANCELLED"
    booking["rejection_reason"] = data["rejection_reason"]
    booking["updated_at"] = db.now_iso()
    booking["version"] += 1

    create_audit_log(user_id, role, "booking.rejected", "Booking", booking_id,
                     {"before": {"status": old_status},
                      "after": {"status": "CANCELLED", "rejection_reason": data["rejection_reason"]}})

    # Waitlist promotion
    promote_waitlist(booking["room_id"], booking["start_time"], booking["end_time"],
                     user_id, role)

    return success_response(booking_to_dict(booking))


@bookings_bp.route("/bookings/<booking_id>/check-in", methods=["POST"])
def check_in_booking(booking_id):
    user_id, role = get_auth()
    booking = db.bookings.get(booking_id)
    if not booking:
        raise_error(ERR_BOOKING_NOT_FOUND, "Booking not found")

    data = request.get_json(force=True, silent=True) or {}
    if "version" in data and data["version"] is not None:
        if data["version"] != booking["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")

    if booking["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_BOOKING_STATE, "Booking is not CONFIRMED")

    now = db.utc_now()
    start_dt = parse_dt(booking["start_time"])
    end_dt = parse_dt(booking["end_time"])

    window_start = start_dt - timedelta(minutes=15)
    if now < window_start or now >= end_dt:
        raise_error(ERR_CHECKIN_WINDOW, "Check-in only allowed within 15 minutes before start through end")

    old_status = booking["status"]
    booking["status"] = "CHECKED_IN"
    booking["checked_in_at"] = db.now_iso()
    booking["updated_at"] = db.now_iso()
    booking["version"] += 1

    create_audit_log(user_id, role, "booking.checked_in", "Booking", booking_id,
                     {"before": {"status": old_status}, "after": {"status": "CHECKED_IN"}})

    return success_response(booking_to_dict(booking))


@bookings_bp.route("/bookings/<booking_id>/check-out", methods=["POST"])
def check_out_booking(booking_id):
    user_id, role = get_auth()
    booking = db.bookings.get(booking_id)
    if not booking:
        raise_error(ERR_BOOKING_NOT_FOUND, "Booking not found")

    data = request.get_json(force=True, silent=True) or {}
    if "version" in data and data["version"] is not None:
        if data["version"] != booking["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")

    if booking["status"] != "CHECKED_IN":
        raise_error(ERR_INVALID_BOOKING_STATE, "Booking is not CHECKED_IN")

    old_status = booking["status"]
    booking["status"] = "COMPLETED"
    booking["updated_at"] = db.now_iso()
    booking["version"] += 1

    create_audit_log(user_id, role, "booking.completed", "Booking", booking_id,
                     {"before": {"status": old_status}, "after": {"status": "COMPLETED"}})

    return success_response(booking_to_dict(booking))


@bookings_bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    user_id, role = get_auth()
    booking = db.bookings.get(booking_id)
    if not booking:
        raise_error(ERR_BOOKING_NOT_FOUND, "Booking not found")

    data = request.get_json(force=True, silent=True) or {}
    if "version" in data and data["version"] is not None:
        if data["version"] != booking["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")

    if booking["status"] not in ("TENTATIVE", "PENDING_APPROVAL", "CONFIRMED"):
        raise_error(ERR_INVALID_BOOKING_STATE,
                    "Booking can only be cancelled from TENTATIVE, PENDING_APPROVAL, or CONFIRMED")

    old_status = booking["status"]
    booking["status"] = "CANCELLED"
    booking["updated_at"] = db.now_iso()
    booking["version"] += 1

    create_audit_log(user_id, role, "booking.cancelled", "Booking", booking_id,
                     {"before": {"status": old_status}, "after": {"status": "CANCELLED"}})

    # Waitlist promotion
    promote_waitlist(booking["room_id"], booking["start_time"], booking["end_time"],
                     user_id, role)

    return success_response(booking_to_dict(booking))
