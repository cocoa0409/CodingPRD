"""Booking endpoints: reserve, arrive, depart, cancel (PRD §3.4)."""

from flask import request, Blueprint

import errors
import serializers
import services
from db import db
from clock import parse_iso
from errors import err
from helpers import get_body, require_str, require_fk, require_int, require_datetime, get_pagination, paginate
from lookups import get_booking, get_truck, get_spot, get_event
from middleware import require_user_context, require_role, require_truck_ownership
from response import ok_object, ok_array

bp = Blueprint("bookings", __name__)

CREATE_ROLES = {"OperatorTruck", "Dispatcher", "PlatformAdmin"}
READ_ROLES = {"Dispatcher", "PlatformAdmin", "OperatorTruck", "HealthInspector"}
ACTION_ROLES = {"OperatorTruck", "PlatformAdmin"}


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test."""
    return a_start < b_end and b_start < a_end


@bp.post("/bookings")
def create_booking():
    user_id, role = require_user_context()
    require_role(role, CREATE_ROLES)
    body = get_body()
    # FK existence (priority 4) before other well-formedness (priority 5).
    truck_id = require_fk(body, "truck_id")
    spot_id = require_fk(body, "spot_id")
    event_id = require_fk(body, "event_id")
    truck = get_truck(truck_id)
    spot = get_spot(spot_id)
    event = get_event(event_id)

    # Entity-backed ownership: OperatorTruck may only book for itself.
    require_truck_ownership(user_id, role, truck_id)

    # Well-formedness (priority 5): window ordering + required OCC field.
    window_start = require_datetime(body, "window_start")
    window_end = require_datetime(body, "window_end")
    expected_truck_version = require_int(body, "expected_truck_version")
    if not (window_end > window_start):
        raise err(errors.ERR_INVALID_REQUEST, "window_end must be after window_start")

    # Priority 11: spot temporal-overlap capacity check.
    buffer = spot["buffer_minutes"]
    import datetime
    pad = datetime.timedelta(minutes=buffer)
    new_start = window_start - pad
    new_end = window_end + pad
    overlapping = 0
    for b in db.bookings.values():
        if b["spot_id"] != spot_id:
            continue
        if b["status"] not in ("RESERVED", "ARRIVED", "DEPARTED"):
            continue
        ex_start = parse_iso(b["window_start"]) - pad
        ex_end = parse_iso(b["window_end"]) + pad
        if _intervals_overlap(new_start, new_end, ex_start, ex_end):
            overlapping += 1
    if overlapping + 1 > spot["concurrent_capacity"]:
        raise err(errors.ERR_SPOT_CAPACITY_EXCEEDED, "Spot concurrent capacity exceeded")

    # Priority 14: booking window within event window [starts_at, ends_at].
    ev_start = parse_iso(event["starts_at"])
    ev_end = parse_iso(event["ends_at"])
    if not (window_start >= ev_start and window_end <= ev_end):
        raise err(errors.ERR_BOOKING_OUTSIDE_EVENT,
                  "Booking window is not contained within the event window")

    # Priority 16: optimistic concurrency on truck.version.
    if expected_truck_version != truck["version"]:
        raise err(errors.ERR_STALE_TRUCK_VERSION,
                  "expected_truck_version does not match the truck's current version")

    rec = db.new_record({
        "truck_id": truck_id,
        "spot_id": spot_id,
        "event_id": event_id,
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "status": "RESERVED",
        "reservation_fee_cents": spot["reservation_fee_cents"],
        "fee_refunded_cents": 0,
    })
    db.bookings[rec["id"]] = rec
    # Create increments the truck's version by 1 (§3.4).
    db.touch(truck)
    return ok_object(serializers.booking(rec), 201)


@bp.get("/bookings")
def list_bookings():
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    records = list(db.bookings.values())
    for field in ("truck_id", "spot_id", "event_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    window, total = paginate(records, limit, offset)
    return ok_array([serializers.booking(r) for r in window], limit, offset, total)


@bp.get("/bookings/<booking_id>")
def get_booking_route(booking_id):
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    rec = get_booking(booking_id)
    return ok_object(serializers.booking(rec))


@bp.post("/bookings/<booking_id>/arrive")
def arrive_booking(booking_id):
    user_id, role = require_user_context()
    require_role(role, ACTION_ROLES)
    rec = get_booking(booking_id)
    require_truck_ownership(user_id, role, rec["truck_id"])
    # Priority 6: booking RESERVED.
    if rec["status"] != "RESERVED":
        raise err(errors.ERR_BOOKING_NOT_RESERVED, "Booking is not RESERVED")
    truck = db.trucks.get(rec["truck_id"])
    # Priority 7: owning truck OPERABLE.
    if truck is None or truck["operability"] != "OPERABLE":
        raise err(errors.ERR_TRUCK_NOT_OPERABLE, "Owning truck is not OPERABLE")
    # Priority 8: parent event SCHEDULED.
    event = db.events.get(rec["event_id"])
    if event is None or event["status"] != "SCHEDULED":
        raise err(errors.ERR_EVENT_NOT_SCHEDULED, "Parent event is not SCHEDULED")
    # Priority 9: clock within [window_start, window_end).
    now = db.clock
    if not (parse_iso(rec["window_start"]) <= now < parse_iso(rec["window_end"])):
        raise err(errors.ERR_OUTSIDE_BOOKING_WINDOW, "Current clock is outside the booking window")
    rec["status"] = "ARRIVED"
    db.touch(rec)
    return ok_object(serializers.booking(rec))


@bp.post("/bookings/<booking_id>/depart")
def depart_booking(booking_id):
    user_id, role = require_user_context()
    require_role(role, ACTION_ROLES)
    rec = get_booking(booking_id)
    require_truck_ownership(user_id, role, rec["truck_id"])
    # Priority 6: booking ARRIVED.
    if rec["status"] != "ARRIVED":
        raise err(errors.ERR_BOOKING_NOT_ARRIVED, "Booking is not ARRIVED")
    # No OPEN order under this booking.
    if services.has_open_order_under_booking(rec["id"]):
        raise err(errors.ERR_OPEN_ORDERS_EXIST, "An OPEN order still exists under this booking")
    rec["status"] = "DEPARTED"
    db.touch(rec)
    return ok_object(serializers.booking(rec))


@bp.post("/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    user_id, role = require_user_context()
    require_role(role, ACTION_ROLES)
    rec = get_booking(booking_id)
    require_truck_ownership(user_id, role, rec["truck_id"])
    # Priority 6: booking RESERVED.
    if rec["status"] != "RESERVED":
        raise err(errors.ERR_BOOKING_NOT_RESERVED, "Booking is not RESERVED")
    # Refund depends on timing relative to the cancellation cutoff (§3.4).
    import datetime
    now = db.clock
    cutoff = parse_iso(rec["window_start"]) - datetime.timedelta(minutes=services.CANCEL_CUTOFF_MINUTES)
    rec["status"] = "CANCELLED"
    if now < cutoff:
        rec["fee_refunded_cents"] = rec["reservation_fee_cents"]
    else:
        rec["fee_refunded_cents"] = 0
    db.touch(rec)
    return ok_object(serializers.booking(rec))
