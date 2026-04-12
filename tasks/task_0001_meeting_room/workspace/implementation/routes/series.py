from flask import Blueprint, request
from datetime import datetime, timedelta, timezone, date
import db
from errors import raise_error, ERR_SERIES_NOT_FOUND, ERR_BAD_REQUEST, ERR_VERSION_CONFLICT, \
    ERR_ROOM_NOT_FOUND, ERR_ROOM_NOT_ACTIVE, ERR_CAPACITY_EXCEEDED, ERR_INVALID_SERIES_RANGE, \
    ERR_EMPTY_SERIES, ERR_INVALID_TIME_RANGE, ERR_BOOKING_TOO_SHORT, ERR_BOOKING_TOO_LONG, \
    ERR_BOOKING_IN_PAST, ERR_INVALID_SERIES_STATE
from middleware import get_auth
from response import success_response
from services.audit import create_audit_log
from services.cost import compute_cost_cents
from services.overlap import has_overlap, parse_dt
from services.waitlist_service import promote_waitlist

series_bp = Blueprint("series", __name__)


def series_to_dict(s):
    return dict(s)


def _generate_occurrences(rule, start_date, end_date, start_time_hhmm, duration_minutes):
    """Generate occurrence dates based on recurrence rule.
    Returns list of (start_datetime, end_datetime) as UTC datetimes.
    """
    occurrences = []
    hour, minute = map(int, start_time_hhmm.split(":"))
    dur = timedelta(minutes=duration_minutes)

    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    if isinstance(end_date, str):
        end_date = date.fromisoformat(end_date)

    if rule == "DAILY":
        step = timedelta(days=1)
    elif rule == "WEEKLY":
        step = timedelta(weeks=1)
    elif rule == "BIWEEKLY":
        step = timedelta(weeks=2)
    else:
        return occurrences

    current_date = start_date
    while current_date <= end_date:
        start_dt = datetime(current_date.year, current_date.month, current_date.day,
                            hour, minute, tzinfo=timezone.utc)
        end_dt = start_dt + dur
        occurrences.append((start_dt, end_dt))
        current_date += step

    return occurrences


@series_bp.route("/series", methods=["POST"])
def create_series():
    user_id, role = get_auth()
    data = request.get_json(force=True, silent=True)
    if not data:
        raise_error(ERR_BAD_REQUEST, "Request body is required")

    for field in ("room_id", "title", "recurrence_rule", "start_time",
                  "duration_minutes", "attendee_count", "series_start_date", "series_end_date"):
        if field not in data or data[field] is None:
            raise_error(ERR_BAD_REQUEST, f"Missing required field: {field}")

    room_id = data["room_id"]
    room = db.rooms.get(room_id)
    if not room:
        raise_error(ERR_ROOM_NOT_FOUND, "Room not found")
    if room["status"] != "ACTIVE":
        raise_error(ERR_ROOM_NOT_ACTIVE, "Room is not ACTIVE")

    recurrence_rule = data["recurrence_rule"]
    if recurrence_rule not in ("DAILY", "WEEKLY", "BIWEEKLY"):
        raise_error(ERR_BAD_REQUEST, "recurrence_rule must be DAILY, WEEKLY, or BIWEEKLY")

    duration_minutes = data["duration_minutes"]
    if not isinstance(duration_minutes, int) or duration_minutes < 1:
        raise_error(ERR_BAD_REQUEST, "duration_minutes must be a positive integer")

    # Temporal validations on duration
    if duration_minutes < 15:
        raise_error(ERR_BOOKING_TOO_SHORT, "Booking must be at least 15 minutes")
    if duration_minutes > 480:
        raise_error(ERR_BOOKING_TOO_LONG, "Booking must not exceed 8 hours")

    attendee_count = data["attendee_count"]
    if not isinstance(attendee_count, int) or attendee_count < 1:
        raise_error(ERR_BAD_REQUEST, "attendee_count must be a positive integer")
    if attendee_count > room["capacity"]:
        raise_error(ERR_CAPACITY_EXCEEDED, "Attendee count exceeds room capacity")

    series_start_date = data["series_start_date"]
    series_end_date = data["series_end_date"]

    try:
        sd = date.fromisoformat(series_start_date)
        ed = date.fromisoformat(series_end_date)
    except (ValueError, TypeError):
        raise_error(ERR_BAD_REQUEST, "Invalid date format for series dates")

    if ed <= sd:
        raise_error(ERR_INVALID_SERIES_RANGE, "series_end_date must be after series_start_date")

    start_time_hhmm = data["start_time"]

    # Generate occurrences
    occurrences = _generate_occurrences(recurrence_rule, sd, ed, start_time_hhmm, duration_minutes)

    # Filter out past occurrences
    now = db.utc_now()
    future_occurrences = [(s, e) for s, e in occurrences if s > now]

    if not future_occurrences:
        raise_error(ERR_EMPTY_SERIES, "Series produces zero booking occurrences")

    # Create series record
    series_id = db.gen_id()
    now_iso = db.now_iso()
    series_record = {
        "id": series_id,
        "room_id": room_id,
        "organizer_id": user_id,
        "title": data["title"],
        "recurrence_rule": recurrence_rule,
        "start_time": start_time_hhmm,
        "duration_minutes": duration_minutes,
        "attendee_count": attendee_count,
        "series_start_date": series_start_date,
        "series_end_date": series_end_date,
        "status": "ACTIVE",
        "total_bookings": len(future_occurrences),
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.series[series_id] = series_record

    create_audit_log(user_id, role, "series.created", "Series", series_id,
                     {"after": dict(series_record)})

    # Generate individual bookings for each occurrence
    for start_dt, end_dt in future_occurrences:
        start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        booking_id = db.gen_id()
        b_now = db.now_iso()
        booking = {
            "id": booking_id,
            "room_id": room_id,
            "organizer_id": user_id,
            "title": data["title"],
            "start_time": start_str,
            "end_time": end_str,
            "attendee_count": attendee_count,
            "status": "TENTATIVE",
            "series_id": series_id,
            "cost_cents": None,
            "rejection_reason": None,
            "checked_in_at": None,
            "created_at": b_now,
            "updated_at": b_now,
            "version": 1,
        }
        db.bookings[booking_id] = booking

        create_audit_log(user_id, role, "booking.created", "Booking", booking_id,
                         {"after": dict(booking), "series_id": series_id})

        # Auto-transition based on tier
        if room["tier"] == "STANDARD":
            if not has_overlap(room_id, start_dt, end_dt, exclude_booking_id=booking_id):
                cost = compute_cost_cents(room, start_dt, end_dt)
                booking["status"] = "CONFIRMED"
                booking["cost_cents"] = cost
                booking["updated_at"] = db.now_iso()
                booking["version"] += 1
                create_audit_log(user_id, role, "booking.confirmed", "Booking", booking_id,
                                 {"before": {"status": "TENTATIVE"},
                                  "after": {"status": "CONFIRMED", "cost_cents": cost}})
            # If conflict, leave as TENTATIVE
        else:
            booking["status"] = "PENDING_APPROVAL"
            booking["updated_at"] = db.now_iso()
            booking["version"] += 1
            create_audit_log(user_id, role, "booking.pending_approval", "Booking", booking_id,
                             {"before": {"status": "TENTATIVE"},
                              "after": {"status": "PENDING_APPROVAL"}})

    return success_response(series_to_dict(series_record), 201)


@series_bp.route("/series/<series_id>", methods=["GET"])
def get_series(series_id):
    get_auth()
    s = db.series.get(series_id)
    if not s:
        raise_error(ERR_SERIES_NOT_FOUND, "Series not found")

    result = dict(s)
    # Include linked bookings
    result["bookings"] = [dict(b) for b in db.bookings.values() if b.get("series_id") == series_id]
    result["bookings"].sort(key=lambda x: x["start_time"])

    return success_response(result)


@series_bp.route("/series/<series_id>/cancel", methods=["POST"])
def cancel_series(series_id):
    user_id, role = get_auth()
    s = db.series.get(series_id)
    if not s:
        raise_error(ERR_SERIES_NOT_FOUND, "Series not found")

    data = request.get_json(force=True, silent=True) or {}
    if "version" in data and data["version"] is not None:
        if data["version"] != s["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")

    if s["status"] != "ACTIVE":
        raise_error(ERR_INVALID_SERIES_STATE, "Series is not ACTIVE")

    old_status = s["status"]
    s["status"] = "CANCELLED"
    s["updated_at"] = db.now_iso()
    s["version"] += 1

    create_audit_log(user_id, role, "series.cancelled", "Series", series_id,
                     {"before": {"status": old_status}, "after": {"status": "CANCELLED"}})

    # Cancel all future non-terminal bookings in this series
    now = db.utc_now()
    for b in list(db.bookings.values()):
        if b.get("series_id") != series_id:
            continue
        if b["status"] not in ("TENTATIVE", "PENDING_APPROVAL", "CONFIRMED"):
            continue
        try:
            b_start = parse_dt(b["start_time"])
        except (ValueError, TypeError):
            continue

        old_b_status = b["status"]
        b["status"] = "CANCELLED"
        b["updated_at"] = db.now_iso()
        b["version"] += 1

        create_audit_log(user_id, role, "booking.cancelled", "Booking", b["id"],
                         {"before": {"status": old_b_status}, "after": {"status": "CANCELLED"},
                          "reason": "series_cancelled"})

        # Trigger waitlist promotion for freed slots
        if old_b_status == "CONFIRMED":
            promote_waitlist(b["room_id"], b["start_time"], b["end_time"], user_id, role)

    result = dict(s)
    result["bookings"] = [dict(b) for b in db.bookings.values() if b.get("series_id") == series_id]
    result["bookings"].sort(key=lambda x: x["start_time"])

    return success_response(result)
