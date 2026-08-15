"""LoadSlot, DockDoor, FreightBooking routes."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import fail
from helpers import (get_json_body, require_str, require_int, require_enum,
                     parse_dt, paginate, sort_by_created, get_or_404)
from middleware import require_roles
from response import success_object, success_list

bp = Blueprint("freight", __name__)

BUFFER = timedelta(minutes=15)


def slot_view(s):
    return {k: s[k] for k in (
        "id", "convention_id", "direction", "starts_at", "ends_at",
        "pallet_capacity", "reserved_pallets", "status",
        "created_at", "updated_at", "version")}


def door_view(d):
    return {k: d[k] for k in ("id", "convention_id", "door_code", "created_at")}


def booking_view(b):
    return {k: b[k] for k in (
        "id", "application_id", "exhibitor_id", "load_slot_id", "dock_door_id",
        "door_starts_at", "door_ends_at", "pallet_count", "status",
        "created_at", "updated_at", "version")}


# ---------------------------------------------------------------------------
# Load slots
# ---------------------------------------------------------------------------
@bp.route("/load-slots", methods=["POST"])
def create_load_slot():
    require_roles("ShowDirector")
    body = get_json_body()
    convention_id = require_str(body, "convention_id")
    direction = require_enum(body, "direction", ("INBOUND", "OUTBOUND"))
    starts_at = parse_dt(body, "starts_at")
    ends_at = parse_dt(body, "ends_at")
    pallet_capacity = require_int(body, "pallet_capacity", minimum=1)
    if db.conventions.get(convention_id) is None:
        fail("ERR_NOT_FOUND", "convention_id does not exist")
    if not ends_at > starts_at:
        fail("ERR_INVALID_TIME_WINDOW", "ends_at must be strictly after starts_at")
    s = {
        "id": db.new_id(),
        "convention_id": convention_id,
        "direction": direction,
        "starts_at": db._fmt_iso(starts_at),
        "ends_at": db._fmt_iso(ends_at),
        "pallet_capacity": pallet_capacity,
        "reserved_pallets": 0,
        "status": "OPEN",
    }
    db.stamp_created(s)
    db.load_slots[s["id"]] = s
    return success_object(slot_view(s), 201)


@bp.route("/load-slots", methods=["GET"])
def list_load_slots():
    require_roles("ShowDirector", "OperationsStaff", "Exhibitor")
    items = list(db.load_slots.values())
    for f in ("convention_id", "direction", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s[f] == v]
    items = sort_by_created(items)
    limit, offset, total, page = paginate(items)
    return success_list([slot_view(s) for s in page], limit, offset, total)


@bp.route("/load-slots/<loadSlotId>", methods=["GET"])
def get_load_slot(loadSlotId):
    require_roles("ShowDirector", "OperationsStaff", "Exhibitor")
    s = get_or_404(db.load_slots, loadSlotId)
    return success_object(slot_view(s), 200)


# ---------------------------------------------------------------------------
# Dock doors
# ---------------------------------------------------------------------------
@bp.route("/dock-doors", methods=["GET"])
def list_dock_doors():
    require_roles("ShowDirector", "OperationsStaff", "Exhibitor")
    items = list(db.dock_doors.values())
    for f in ("convention_id", "door_code"):
        v = request.args.get(f)
        if v is not None:
            items = [d for d in items if d[f] == v]
    items = sort_by_created(items)
    limit, offset, total, page = paginate(items)
    return success_list([door_view(d) for d in page], limit, offset, total)


@bp.route("/dock-doors/<dockDoorId>", methods=["GET"])
def get_dock_door(dockDoorId):
    require_roles("ShowDirector", "OperationsStaff", "Exhibitor")
    d = get_or_404(db.dock_doors, dockDoorId)
    return success_object(door_view(d), 200)


# ---------------------------------------------------------------------------
# Freight bookings
# ---------------------------------------------------------------------------
@bp.route("/freight-bookings", methods=["POST"])
def create_freight_booking():
    user_id, _ = require_roles("Exhibitor")
    body = get_json_body()
    application_id = require_str(body, "application_id")
    load_slot_id = require_str(body, "load_slot_id")
    dock_door_id = require_str(body, "dock_door_id")
    door_starts_at = parse_dt(body, "door_starts_at")
    door_ends_at = parse_dt(body, "door_ends_at")
    pallet_count = require_int(body, "pallet_count", minimum=1)

    a = db.applications.get(application_id)
    if a is None:
        fail("ERR_NOT_FOUND", "application_id does not exist")
    slot = db.load_slots.get(load_slot_id)
    if slot is None:
        fail("ERR_NOT_FOUND", "load_slot_id does not exist")
    door = db.dock_doors.get(dock_door_id)
    if door is None:
        fail("ERR_NOT_FOUND", "dock_door_id does not exist")
    # ownership
    if a["exhibitor_id"] != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Exhibitor role: own applications only")
    # state: slot must be OPEN before any clock reasoning
    if slot["status"] != "OPEN":
        fail("ERR_INVALID_TRANSITION", "Load slot must be OPEN")
    # temporal: phase gate by slot direction
    conv = db.conventions[a["convention_id"]]
    if slot["direction"] == "INBOUND":
        if conv["phase"] != "LOGISTICS":
            fail("ERR_FREIGHT_WRONG_PHASE", "INBOUND bookings require phase LOGISTICS")
    else:
        if conv["phase"] != "LOAD_OUT":
            fail("ERR_FREIGHT_WRONG_PHASE", "OUTBOUND bookings require phase LOAD_OUT")
    # referential: application PLACED
    if a["status"] != "PLACED":
        fail("ERR_APPLICATION_NOT_PLACED", "Application must be PLACED")
    # door window inside slot window
    slot_start = db._parse_iso(slot["starts_at"])
    slot_end = db._parse_iso(slot["ends_at"])
    if not (door_starts_at >= slot_start and door_ends_at <= slot_end):
        fail("ERR_DOOR_WINDOW_OUTSIDE_SLOT",
             "Door window must lie inside the slot window")
    if not door_ends_at > door_starts_at:
        fail("ERR_INVALID_TIME_WINDOW", "door_ends_at must be after door_starts_at")
    # buffered overlap against active bookings on the same door
    for fb in db.freight_bookings.values():
        if fb["dock_door_id"] != dock_door_id:
            continue
        if fb["status"] not in ("REQUESTED", "CONFIRMED", "CHECKED_IN"):
            continue
        s = db._parse_iso(fb["door_starts_at"])
        e = db._parse_iso(fb["door_ends_at"])
        if door_starts_at < e + BUFFER and s < door_ends_at + BUFFER:
            fail("ERR_DOOR_WINDOW_CONFLICT",
                 "Door occupation collides with an active booking (15-minute buffer)")
    # capacity last
    if slot["reserved_pallets"] + pallet_count > slot["pallet_capacity"]:
        fail("ERR_SLOT_CAPACITY_EXCEEDED",
             "reserved_pallets + pallet_count would exceed pallet_capacity")

    b = {
        "id": db.new_id(),
        "application_id": application_id,
        "exhibitor_id": a["exhibitor_id"],
        "load_slot_id": load_slot_id,
        "dock_door_id": dock_door_id,
        "door_starts_at": db._fmt_iso(door_starts_at),
        "door_ends_at": db._fmt_iso(door_ends_at),
        "pallet_count": pallet_count,
        "status": "REQUESTED",
    }
    db.stamp_created(b)
    db.freight_bookings[b["id"]] = b
    slot["reserved_pallets"] += pallet_count
    if slot["reserved_pallets"] >= slot["pallet_capacity"]:
        slot["status"] = "FULL"
    db.touch(slot)
    return success_object(booking_view(b), 201)


@bp.route("/freight-bookings", methods=["GET"])
def list_freight_bookings():
    user_id, role = require_roles("ShowDirector", "OperationsStaff", "Exhibitor")
    items = list(db.freight_bookings.values())
    if role == "Exhibitor":
        items = [b for b in items if b["exhibitor_id"] == user_id]
    for f in ("application_id", "exhibitor_id", "load_slot_id", "dock_door_id", "status"):
        v = request.args.get(f)
        if v is not None:
            if role == "Exhibitor" and f == "exhibitor_id":
                continue
            items = [b for b in items if b[f] == v]
    items = sort_by_created(items)
    limit, offset, total, page = paginate(items)
    return success_list([booking_view(b) for b in page], limit, offset, total)


@bp.route("/freight-bookings/<freightBookingId>", methods=["GET"])
def get_freight_booking(freightBookingId):
    user_id, role = require_roles("ShowDirector", "OperationsStaff", "Exhibitor")
    b = get_or_404(db.freight_bookings, freightBookingId)
    if role == "Exhibitor" and b["exhibitor_id"] != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Exhibitor role: own bookings only")
    return success_object(booking_view(b), 200)


@bp.route("/freight-bookings/<freightBookingId>/confirm", methods=["POST"])
def confirm_freight_booking(freightBookingId):
    require_roles("OperationsStaff", "ShowDirector")
    b = get_or_404(db.freight_bookings, freightBookingId)
    if b["status"] != "REQUESTED":
        fail("ERR_INVALID_TRANSITION", "confirm requires REQUESTED")
    b["status"] = "CONFIRMED"
    db.touch(b)
    return success_object(booking_view(b), 200)


@bp.route("/freight-bookings/<freightBookingId>/cancel", methods=["POST"])
def cancel_freight_booking(freightBookingId):
    user_id, role = require_roles("Exhibitor", "OperationsStaff", "ShowDirector")
    b = get_or_404(db.freight_bookings, freightBookingId)
    if role == "Exhibitor" and b["exhibitor_id"] != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Exhibitor role: own bookings only")
    if b["status"] not in ("REQUESTED", "CONFIRMED"):
        fail("ERR_INVALID_TRANSITION", "cancel requires REQUESTED or CONFIRMED")
    b["status"] = "CANCELLED"
    db.touch(b)
    slot = db.load_slots.get(b["load_slot_id"])
    if slot is not None:
        slot["reserved_pallets"] = max(0, slot["reserved_pallets"] - b["pallet_count"])
        if slot["status"] == "FULL" and slot["reserved_pallets"] < slot["pallet_capacity"]:
            slot["status"] = "OPEN"
        db.touch(slot)
    return success_object(booking_view(b), 200)


@bp.route("/freight-bookings/<freightBookingId>/check-in", methods=["POST"])
def check_in_freight_booking(freightBookingId):
    require_roles("OperationsStaff")
    b = get_or_404(db.freight_bookings, freightBookingId)
    if b["status"] != "CONFIRMED":
        fail("ERR_INVALID_TRANSITION", "check-in requires CONFIRMED")
    slot = db.load_slots[b["load_slot_id"]]
    now = db.now_dt()
    if not (db._parse_iso(slot["starts_at"]) <= now < db._parse_iso(slot["ends_at"])):
        fail("ERR_INVALID_TIME_WINDOW",
             "Clock must be inside the load slot window")
    b["status"] = "CHECKED_IN"
    db.touch(b)
    return success_object(booking_view(b), 200)
