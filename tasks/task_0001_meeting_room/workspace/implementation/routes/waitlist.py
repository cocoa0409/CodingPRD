from flask import Blueprint, request
from datetime import timedelta
import db
from errors import raise_error, ERR_WAITLIST_NOT_FOUND, ERR_BAD_REQUEST, ERR_VERSION_CONFLICT, \
    ERR_ROOM_NOT_FOUND, ERR_ROOM_NOT_ACTIVE, ERR_INVALID_WAITLIST_STATE, ERR_DUPLICATE_WAITLIST, \
    ERR_INVALID_TIME_RANGE, ERR_BOOKING_IN_PAST, ERR_CAPACITY_EXCEEDED
from middleware import get_auth
from response import success_response, list_response
from services.audit import create_audit_log
from services.overlap import parse_dt
from services.waitlist_service import reposition_waitlist

waitlist_bp = Blueprint("waitlist", __name__)


def waitlist_to_dict(w):
    return dict(w)


@waitlist_bp.route("/waitlist", methods=["POST"])
def create_waitlist_entry():
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

    # Validate time range
    try:
        start_dt = parse_dt(data["start_time"])
        end_dt = parse_dt(data["end_time"])
    except (ValueError, TypeError):
        raise_error(ERR_BAD_REQUEST, "Invalid datetime format")

    if end_dt <= start_dt:
        raise_error(ERR_INVALID_TIME_RANGE, "end_time must be after start_time")

    now = db.utc_now()
    if start_dt <= now:
        raise_error(ERR_BOOKING_IN_PAST, "start_time must be in the future")

    attendee_count = data["attendee_count"]
    if not isinstance(attendee_count, int) or attendee_count < 1:
        raise_error(ERR_BAD_REQUEST, "attendee_count must be a positive integer")
    if attendee_count > room["capacity"]:
        raise_error(ERR_CAPACITY_EXCEEDED, "Attendee count exceeds room capacity")

    # Duplicate check
    for w in db.waitlist.values():
        if (w["room_id"] == room_id and
            w["requester_id"] == user_id and
            w["start_time"] == data["start_time"] and
            w["end_time"] == data["end_time"] and
            w["status"] == "WAITING"):
            raise_error(ERR_DUPLICATE_WAITLIST,
                        "Duplicate waitlist entry for same requester, room, and time window")

    # Assign position
    existing_waiting = [w for w in db.waitlist.values()
                        if w["room_id"] == room_id and w["status"] == "WAITING"]
    position = len(existing_waiting) + 1

    now_iso = db.now_iso()
    entry_id = db.gen_id()
    entry = {
        "id": entry_id,
        "room_id": room_id,
        "requester_id": user_id,
        "title": data["title"],
        "start_time": data["start_time"],
        "end_time": data["end_time"],
        "attendee_count": attendee_count,
        "status": "WAITING",
        "position": position,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.waitlist[entry_id] = entry

    create_audit_log(user_id, role, "waitlist.created", "Waitlist", entry_id,
                     {"after": dict(entry)})

    return success_response(waitlist_to_dict(entry), 201)


@waitlist_bp.route("/waitlist", methods=["GET"])
def list_waitlist():
    get_auth()
    args = request.args

    filtered = list(db.waitlist.values())

    if "room_id" in args:
        filtered = [w for w in filtered if w["room_id"] == args["room_id"]]
    if "requester_id" in args:
        filtered = [w for w in filtered if w["requester_id"] == args["requester_id"]]
    if "status" in args:
        filtered = [w for w in filtered if w["status"] == args["status"]]

    filtered.sort(key=lambda x: x["created_at"])
    total_count = len(filtered)

    limit = min(max(int(args.get("limit", 20)), 1), 100)
    offset = max(int(args.get("offset", 0)), 0)

    page = filtered[offset:offset + limit]
    return list_response([waitlist_to_dict(w) for w in page], total_count, limit, offset)


@waitlist_bp.route("/waitlist/<waitlist_id>", methods=["DELETE"])
def cancel_waitlist_entry(waitlist_id):
    user_id, role = get_auth()
    entry = db.waitlist.get(waitlist_id)
    if not entry:
        raise_error(ERR_WAITLIST_NOT_FOUND, "Waitlist entry not found")

    # Version check via request body or query
    data = request.get_json(force=True, silent=True) or {}
    if "version" in data and data["version"] is not None:
        if data["version"] != entry["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")

    if entry["status"] != "WAITING":
        raise_error(ERR_INVALID_WAITLIST_STATE, "Waitlist entry is not WAITING")

    old_status = entry["status"]
    entry["status"] = "CANCELLED"
    entry["updated_at"] = db.now_iso()
    entry["version"] += 1

    create_audit_log(user_id, role, "waitlist.cancelled", "Waitlist", waitlist_id,
                     {"before": {"status": old_status}, "after": {"status": "CANCELLED"}})

    # Re-position remaining entries
    reposition_waitlist(entry["room_id"])

    return success_response(waitlist_to_dict(entry))
