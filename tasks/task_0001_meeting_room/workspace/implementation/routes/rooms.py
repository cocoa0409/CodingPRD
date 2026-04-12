from flask import Blueprint, request
import db
from errors import raise_error, ERR_ROOM_NOT_FOUND, ERR_BAD_REQUEST, ERR_VERSION_CONFLICT, \
    ERR_ROOM_NOT_ACTIVE, ERR_ROOM_HAS_ACTIVE_BOOKINGS, ERR_ROOM_NAME_TAKEN
from middleware import require_roles, get_auth
from response import success_response, list_response
from services.audit import create_audit_log
from services.waitlist_service import promote_waitlist

rooms_bp = Blueprint("rooms", __name__)


def room_to_dict(r):
    return dict(r)


@rooms_bp.route("/rooms", methods=["POST"])
def create_room():
    user_id, role = require_roles("facility_admin")
    data = request.get_json(force=True, silent=True)
    if not data:
        raise_error(ERR_BAD_REQUEST, "Request body is required")

    # Required fields
    for field in ("name", "capacity", "floor", "tier", "hourly_rate_cents"):
        if field not in data or data[field] is None:
            raise_error(ERR_BAD_REQUEST, f"Missing required field: {field}")

    name = data["name"]
    if not isinstance(name, str) or not name.strip():
        raise_error(ERR_BAD_REQUEST, "name must be a non-empty string")

    # Uniqueness check
    for existing in db.rooms.values():
        if existing["name"] == name:
            raise_error(ERR_ROOM_NAME_TAKEN, "Room name already exists")

    capacity = data["capacity"]
    if not isinstance(capacity, int) or capacity < 1:
        raise_error(ERR_BAD_REQUEST, "capacity must be a positive integer")

    floor_val = data["floor"]
    if not isinstance(floor_val, int):
        raise_error(ERR_BAD_REQUEST, "floor must be an integer")

    tier = data["tier"]
    if tier not in ("STANDARD", "PREMIUM"):
        raise_error(ERR_BAD_REQUEST, "tier must be STANDARD or PREMIUM")

    hourly_rate_cents = data["hourly_rate_cents"]
    if not isinstance(hourly_rate_cents, int) or hourly_rate_cents < 0:
        raise_error(ERR_BAD_REQUEST, "hourly_rate_cents must be a non-negative integer")

    now = db.now_iso()
    room_id = db.gen_id()
    room = {
        "id": room_id,
        "name": name,
        "capacity": capacity,
        "floor": floor_val,
        "amenities": data.get("amenities", []),
        "tier": tier,
        "status": "ACTIVE",
        "hourly_rate_cents": hourly_rate_cents,
        "peak_multiplier": data.get("peak_multiplier", 1.0),
        "peak_hours_start": data.get("peak_hours_start"),
        "peak_hours_end": data.get("peak_hours_end"),
        "ops_run_index": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.rooms[room_id] = room

    create_audit_log(user_id, role, "room.created", "Room", room_id,
                     {"after": dict(room)})

    return success_response(room_to_dict(room), 201)


@rooms_bp.route("/rooms", methods=["GET"])
def list_rooms():
    get_auth()
    args = request.args

    filtered = list(db.rooms.values())

    if "status" in args:
        filtered = [r for r in filtered if r["status"] == args["status"]]
    if "tier" in args:
        filtered = [r for r in filtered if r["tier"] == args["tier"]]
    if "min_capacity" in args:
        try:
            mc = int(args["min_capacity"])
            filtered = [r for r in filtered if r["capacity"] >= mc]
        except ValueError:
            pass
    if "floor" in args:
        try:
            f = int(args["floor"])
            filtered = [r for r in filtered if r["floor"] == f]
        except ValueError:
            pass
    if "amenity" in args:
        amenity = args["amenity"]
        filtered = [r for r in filtered if amenity in r.get("amenities", [])]

    filtered.sort(key=lambda x: x["created_at"])
    total_count = len(filtered)

    limit = min(max(int(args.get("limit", 20)), 1), 100)
    offset = max(int(args.get("offset", 0)), 0)

    page = filtered[offset:offset + limit]
    return list_response([room_to_dict(r) for r in page], total_count, limit, offset)


@rooms_bp.route("/rooms/<room_id>", methods=["GET"])
def get_room(room_id):
    get_auth()
    room = db.rooms.get(room_id)
    if not room:
        raise_error(ERR_ROOM_NOT_FOUND, "Room not found")
    return success_response(room_to_dict(room))


@rooms_bp.route("/rooms/<room_id>", methods=["PUT"])
def update_room(room_id):
    user_id, role = require_roles("facility_admin")
    room = db.rooms.get(room_id)
    if not room:
        raise_error(ERR_ROOM_NOT_FOUND, "Room not found")

    data = request.get_json(force=True, silent=True)
    if not data:
        raise_error(ERR_BAD_REQUEST, "Request body is required")

    # Optimistic concurrency
    if "version" in data and data["version"] is not None:
        if data["version"] != room["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")

    before = dict(room)

    # Check status transition
    new_status = data.get("status")
    if new_status and new_status != room["status"]:
        _handle_status_transition(room, new_status, user_id, role)

    # Update other fields
    for field in ("name", "capacity", "amenities", "tier", "hourly_rate_cents",
                  "peak_multiplier", "peak_hours_start", "peak_hours_end"):
        if field in data:
            if field == "name":
                new_name = data["name"]
                for existing in db.rooms.values():
                    if existing["name"] == new_name and existing["id"] != room_id:
                        raise_error(ERR_ROOM_NAME_TAKEN, "Room name already exists")
            room[field] = data[field]

    room["updated_at"] = db.now_iso()
    room["version"] += 1

    create_audit_log(user_id, role, "room.updated", "Room", room_id,
                     {"before": before, "after": dict(room)})

    return success_response(room_to_dict(room))


def _handle_status_transition(room, new_status, user_id, role):
    current = room["status"]
    valid_transitions = {
        ("ACTIVE", "MAINTENANCE"),
        ("MAINTENANCE", "ACTIVE"),
        ("ACTIVE", "DECOMMISSIONED"),
        ("MAINTENANCE", "DECOMMISSIONED"),
    }
    if (current, new_status) not in valid_transitions:
        raise_error(ERR_BAD_REQUEST, f"Invalid status transition from {current} to {new_status}")

    if new_status == "DECOMMISSIONED":
        # Check no CHECKED_IN bookings
        for b in db.bookings.values():
            if b["room_id"] == room["id"] and b["status"] == "CHECKED_IN":
                raise_error(ERR_ROOM_HAS_ACTIVE_BOOKINGS,
                            "Cannot decommission room while CHECKED_IN bookings exist")

    room["status"] = new_status

    if new_status == "MAINTENANCE":
        _cancel_future_bookings(room["id"], user_id, role,
                                statuses=("TENTATIVE", "PENDING_APPROVAL", "CONFIRMED"))
        _expire_waiting_entries(room["id"], user_id, role, only_future=False)

    elif new_status == "DECOMMISSIONED":
        _cancel_future_bookings(room["id"], user_id, role,
                                statuses=("TENTATIVE", "PENDING_APPROVAL", "CONFIRMED"))
        _expire_all_waiting(room["id"], user_id, role)


def _cancel_future_bookings(room_id, user_id, role, statuses):
    from services.overlap import parse_dt
    now = db.utc_now()
    for b in list(db.bookings.values()):
        if b["room_id"] != room_id:
            continue
        if b["status"] not in statuses:
            continue
        b_start = parse_dt(b["start_time"])
        if b_start <= now:
            continue
        old_status = b["status"]
        b["status"] = "CANCELLED"
        b["updated_at"] = db.now_iso()
        b["version"] += 1
        create_audit_log(user_id, role, "booking.cancelled", "Booking", b["id"],
                         {"before": {"status": old_status}, "after": {"status": "CANCELLED"},
                          "reason": "room_status_change"})


def _expire_waiting_entries(room_id, user_id, role, only_future=False):
    for w in list(db.waitlist.values()):
        if w["room_id"] != room_id or w["status"] != "WAITING":
            continue
        old_status = w["status"]
        w["status"] = "EXPIRED"
        w["updated_at"] = db.now_iso()
        w["version"] += 1
        create_audit_log(user_id, role, "waitlist.expired", "Waitlist", w["id"],
                         {"before": {"status": old_status}, "after": {"status": "EXPIRED"}})


def _expire_all_waiting(room_id, user_id, role):
    _expire_waiting_entries(room_id, user_id, role, only_future=False)


@rooms_bp.route("/rooms/<room_id>/run_ops", methods=["POST"])
def run_ops(room_id):
    user_id, role = require_roles("facility_admin")
    room = db.rooms.get(room_id)
    if not room:
        raise_error(ERR_ROOM_NOT_FOUND, "Room not found")

    from services.overlap import parse_dt
    from datetime import timedelta

    room["ops_run_index"] += 1
    room["updated_at"] = db.now_iso()
    room["version"] += 1

    now = db.utc_now()
    grace = timedelta(minutes=15)

    # No-show detection
    no_show_bookings = []
    for b in list(db.bookings.values()):
        if b["room_id"] != room_id:
            continue
        if b["status"] != "CONFIRMED":
            continue
        b_start = parse_dt(b["start_time"])
        if now > b_start + grace and not b.get("checked_in_at"):
            old_status = b["status"]
            b["status"] = "NO_SHOW"
            b["updated_at"] = db.now_iso()
            b["version"] += 1
            no_show_bookings.append(b)
            create_audit_log(user_id, role, "booking.no_show", "Booking", b["id"],
                             {"before": {"status": old_status}, "after": {"status": "NO_SHOW"}})

    # Waitlist expiry
    for w in list(db.waitlist.values()):
        if w["room_id"] != room_id or w["status"] != "WAITING":
            continue
        w_start = parse_dt(w["start_time"])
        if now > w_start:
            old_status = w["status"]
            w["status"] = "EXPIRED"
            w["updated_at"] = db.now_iso()
            w["version"] += 1
            create_audit_log(user_id, role, "waitlist.expired", "Waitlist", w["id"],
                             {"before": {"status": old_status}, "after": {"status": "EXPIRED"}})

    # Waitlist promotion after no-show frees slots
    for b in no_show_bookings:
        promote_waitlist(room_id, b["start_time"], b["end_time"], user_id, role)

    create_audit_log(user_id, role, "room.ops_run", "Room", room_id,
                     {"ops_run_index": room["ops_run_index"]})

    return success_response(room_to_dict(room))
