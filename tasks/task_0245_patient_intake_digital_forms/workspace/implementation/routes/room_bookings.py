"""RoomBooking routes (PRD §2.7, §3.11). Closed-interval overlap + OCC on room version."""
from flask import Blueprint, request

import clock
import db
import serialize
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_STALE_ROOM_VERSION,
    ERR_ROOM_DOUBLE_BOOKED,
)
from middleware import require_roles
from response import success, success_list
from services import calculations
from services.common import touch, require_string, require_int
from services.lookups import get_exam_room, get_queue_entry, get_room_booking
from services.pagination import paginate

bp = Blueprint("room_bookings", __name__)


@bp.route("/room-bookings", methods=["POST"])
@require_roles("FrontDeskStaff")
def create_room_booking():
    body = request.get_json(silent=True) or {}
    exam_room_id = require_string(body, "exam_room_id")
    queue_entry_id = require_string(body, "queue_entry_id")
    start_raw = require_string(body, "start_utc")
    end_raw = require_string(body, "end_utc")
    expected_version = require_int(body, "expected_exam_room_version")

    # FK existence (PRD §2.5).
    room = get_exam_room(exam_room_id)
    get_queue_entry(queue_entry_id)

    start_utc = clock.parse_instant(start_raw)
    end_utc = clock.parse_instant(end_raw)
    if not (end_utc > start_utc):
        raise err(ERR_INVALID_REQUEST, "end_utc must be strictly after start_utc")

    with db.LOCK:
        # OCC check runs first (PRD §2.7).
        if expected_version != room["version"]:
            raise err(ERR_STALE_ROOM_VERSION, "stale room version")

        # Closed-interval overlap check (PRD §3.11).
        booked = []
        for b in db.room_bookings.values():
            if b["exam_room_id"] != exam_room_id:
                continue
            b_start = clock.parse_instant(b["start_utc"])
            b_end = clock.parse_instant(b["end_utc"])
            booked.append((b_start, b_end))
        if calculations.room_overlap(start_utc, end_utc, booked):
            raise err(ERR_ROOM_DOUBLE_BOOKED, "room double-booked")

        now = db.now_iso()
        booking = {
            "id": db.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": db.next_seq(),
            "exam_room_id": exam_room_id,
            "queue_entry_id": queue_entry_id,
            "start_utc": clock.format_instant(start_utc),
            "end_utc": clock.format_instant(end_utc),
        }
        db.room_bookings[booking["id"]] = booking
        # A successful booking advances the room's version (PRD §2.7, §3.11).
        touch(room)
    return success(serialize.room_booking(booking), status=201)


@bp.route("/room-bookings/<bid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def get_room_booking_route(bid):
    booking = get_room_booking(bid)
    return success(serialize.room_booking(booking), status=200)


@bp.route("/room-bookings", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def list_room_bookings():
    records = list(db.room_bookings.values())
    for f in ("exam_room_id", "queue_entry_id"):
        val = request.args.get(f)
        if val is not None:
            records = [r for r in records if r[f] == val]
    items, limit, offset, total = paginate(records, serialize.room_booking)
    return success_list(items, limit, offset, total)
