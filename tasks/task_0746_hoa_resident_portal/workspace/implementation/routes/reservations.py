"""AmenityReservation: create, list, get, cancel, check-in."""

from flask import Blueprint, request

import db
from auth import require_role
from clock import get_now, get_now_iso, sweep_time_transitions
from entities import bump, new_amenity_reservation
from errors import raise_error
from response import success
from services import reservation as reservation_svc
from utils import (paginate, parse_iso, require_fields, require_int, require_str,
                   require_json)

bp = Blueprint("reservations", __name__)


@bp.route("/amenity-reservations", methods=["POST"])
@require_role("Homeowner")
def create_reservation():
    body = require_json(request)
    require_fields(body, "amenity_id", "homeowner_id", "start_ts", "end_ts", "guest_count")
    amenity_id = require_str(body, "amenity_id")
    homeowner_id = require_str(body, "homeowner_id")
    start_ts = require_str(body, "start_ts")
    end_ts = require_str(body, "end_ts")
    guest_count = require_int(body, "guest_count", minimum=1)

    # FK checks.
    amenity = db.amenities.get(amenity_id)
    if not amenity:
        raise_error("ERR_FK_NOT_FOUND", "amenity_id does not resolve")
    home = db.homeowners.get(homeowner_id)
    if not home:
        raise_error("ERR_FK_NOT_FOUND", "homeowner_id does not resolve")

    sweep_time_transitions()

    # Priority 7 gate: booking_privilege != FROZEN.
    if home.get("booking_privilege") == "FROZEN":
        raise_error("ERR_PROPERTY_SUSPENDED", "homeowner booking privilege is FROZEN")

    # Priority 9: temporal window/blackout.
    reservation_svc.validate_window(amenity, start_ts, end_ts)

    # Priority 11: capacity.
    reservation_svc.check_capacity(amenity, start_ts, end_ts, guest_count)

    now_iso = get_now_iso()
    row = new_amenity_reservation(amenity_id, homeowner_id, start_ts, end_ts, guest_count, now_iso)
    db.amenity_reservations[row["id"]] = row
    return success(row, status=201)


@bp.route("/amenity-reservations", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def list_reservations():
    sweep_time_transitions()
    hid = request.args.get("homeowner_id")
    items = list(db.amenity_reservations.values())
    if hid:
        items = [r for r in items if r["homeowner_id"] == hid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)


@bp.route("/amenity-reservations/<rid>", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def get_reservation(rid):
    sweep_time_transitions()
    r = db.amenity_reservations.get(rid)
    if not r:
        raise_error("ERR_NOT_FOUND", "reservation not found")
    return success(r)


@bp.route("/amenity-reservations/<rid>/cancel", methods=["POST"])
@require_role("Homeowner", "HOAManager")
def cancel_reservation(rid):
    require_json(request)
    sweep_time_transitions()
    r = db.amenity_reservations.get(rid)
    if not r:
        raise_error("ERR_NOT_FOUND", "reservation not found")
    if r["status"] != "BOOKED":
        raise_error("ERR_INVALID_STATE", "only BOOKED reservations may be cancelled")
    if get_now() >= parse_iso(r["start_ts"]):
        raise_error("ERR_INVALID_STATE", "reservation has already started")
    r["status"] = "CANCELLED"
    bump(r, get_now_iso())
    return success(r)


@bp.route("/amenity-reservations/<rid>/check-in", methods=["POST"])
@require_role("HOAManager")
def check_in_reservation(rid):
    require_json(request)
    sweep_time_transitions()
    r = db.amenity_reservations.get(rid)
    if not r:
        raise_error("ERR_NOT_FOUND", "reservation not found")
    if r["status"] != "BOOKED":
        raise_error("ERR_INVALID_STATE", "reservation not BOOKED")
    now_dt = get_now()
    if now_dt < parse_iso(r["start_ts"]):
        raise_error("ERR_INVALID_STATE", "check-in before start_ts")
    if now_dt >= parse_iso(r["end_ts"]):
        raise_error("ERR_INVALID_STATE", "check-in after end_ts")
    r["status"] = "CHECKED_IN"
    bump(r, get_now_iso())
    return success(r)
