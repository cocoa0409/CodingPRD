"""GreenRoomBooking routes."""

from flask import Blueprint, request

from db import DB, CLOCK, new_id, now_ts, parse_iso
from errors import (
    err_not_found, err_not_owner, err_invalid_state, err_booking_in_past,
    err_green_room_inaccessible, err_green_room_full, err_validation,
)
from middleware import require_roles
from response import success
from services.calculations import (
    GREEN_ROOM_CAPACITY, ACCESSIBLE_ROOMS, green_room_overlap_count,
)
from services.helpers import body_json, req_str, req_iso, req_enum, opt_bool
from services.serializers import green_room_booking_view, paginate

bp = Blueprint("green_room_bookings", __name__)

ROOM_NAMES = {"NORTH", "SOUTH", "EAST"}


@bp.route("/green-room-bookings", methods=["POST"])
def create_booking():
    user_id, _ = require_roles("Contestant")
    body = body_json()
    contestant_id = req_str(body, "contestant_id")
    contest_id = req_str(body, "contest_id")
    room_name = req_enum(body, "room_name", ROOM_NAMES)
    start_at = req_iso(body, "start_at")
    end_at = req_iso(body, "end_at")
    requires_accessibility = opt_bool(body, "requires_accessibility_setup", default=False)

    if parse_iso(end_at) <= parse_iso(start_at):
        raise err_validation("end_at must be strictly after start_at")

    # FK resolution (left-to-right).
    contestant = DB.contestants.get(contestant_id)
    if contestant is None:
        raise err_not_found("Contestant not found")
    contest = DB.contest_events.get(contest_id)
    if contest is None:
        raise err_not_found("ContestEvent not found")

    # Ownership.
    if contestant_id != user_id:
        raise err_not_owner("contestant_id must equal caller X-User-ID")

    # Accessibility structural rule (business constraint tier).
    if requires_accessibility and room_name not in ACCESSIBLE_ROOMS:
        raise err_green_room_inaccessible()

    # Temporal: not in the past (logical clock).
    if parse_iso(start_at) < CLOCK.now():
        raise err_booking_in_past()

    # Temporal: capacity by overlap count; exactly 4 overlapping is legal, the
    # request that would make a 5th simultaneous overlap is rejected.
    if green_room_overlap_count(room_name, start_at, end_at) >= GREEN_ROOM_CAPACITY:
        raise err_green_room_full()

    ts = now_ts()
    booking = {
        "id": new_id(),
        "contestant_id": contestant_id,
        "contest_id": contest_id,
        "room_name": room_name,
        "start_at": start_at,
        "end_at": end_at,
        "requires_accessibility_setup": requires_accessibility,
        "status": "BOOKED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB.green_room_bookings[booking["id"]] = booking
    return success(green_room_booking_view(booking), status=201)


@bp.route("/green-room-bookings", methods=["GET"])
def list_bookings():
    require_roles("Contestant", "ContestLead")
    items = list(DB.green_room_bookings.values())
    contestant_id = request.args.get("contestant_id")
    contest_id = request.args.get("contest_id")
    room_name = request.args.get("room_name")
    status = request.args.get("status")
    if contestant_id is not None:
        items = [b for b in items if b["contestant_id"] == contestant_id]
    if contest_id is not None:
        items = [b for b in items if b["contest_id"] == contest_id]
    if room_name is not None:
        items = [b for b in items if b["room_name"] == room_name]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: b["created_at"])
    page, pag = paginate([green_room_booking_view(b) for b in items], request.args)
    return success(page, response_type="array", pagination=pag)


@bp.route("/green-room-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    require_roles("Contestant", "ContestLead")
    booking = DB.green_room_bookings.get(bid)
    if booking is None:
        raise err_not_found("GreenRoomBooking not found")
    return success(green_room_booking_view(booking))


@bp.route("/green-room-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    user_id, _ = require_roles("Contestant")
    booking = DB.green_room_bookings.get(bid)
    if booking is None:
        raise err_not_found("GreenRoomBooking not found")
    if booking["contestant_id"] != user_id:
        raise err_not_owner("Contestant may only cancel own bookings")
    if booking["status"] != "BOOKED":
        raise err_invalid_state("Only BOOKED bookings can be cancelled")
    booking["status"] = "CANCELLED"
    booking["updated_at"] = now_ts()
    booking["version"] += 1
    return success(green_room_booking_view(booking))
