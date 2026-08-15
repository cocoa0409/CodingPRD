"""Practice bookings: half-open windows, kart overlap, track capacity, billing."""
from flask import Blueprint, request

from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_DRIVER_NOT_ACTIVE,
    ERR_KART_UNAVAILABLE,
    ERR_BOOKING_OVERLAP,
    ERR_TRACK_CAPACITY_EXCEEDED,
    ERR_FORBIDDEN,
)
from middleware import authorized, check_driver_ownership, ANY_ROLE
from response import success_object, success_list
from services import core
from util import parse_datetime, whole_minutes, metered_fee_cents, FLAT_SESSION_FEE_CENTS
from validate import json_body, v_id, v_enum, v_datetime

bp = Blueprint("bookings", __name__)

PRICING_MODES = {"FLAT", "METERED"}
_ACTIVE_BOOKING_STATES = ("RESERVED", "CHECKED_IN")


def _windows_intersect(a_start, a_end, b_start, b_end):
    """Half-open interval intersection: touching endpoints do NOT intersect."""
    return a_start < b_end and b_start < a_end


@bp.post("/practice-bookings")
def create_booking():
    caller = authorized(["Driver"])
    body = json_body()
    raw_driver = body.get("driver_id")
    if isinstance(raw_driver, str) and raw_driver != caller.user_id:
        raise_error(ERR_FORBIDDEN, "a Driver may only book for themselves")
    driver_id = v_id(body, "driver_id")
    kart_id = v_id(body, "kart_id")
    start_raw, start_dt = v_datetime(body, "start_time")
    end_raw, end_dt = v_datetime(body, "end_time")
    pricing_mode = v_enum(body, "pricing_mode", PRICING_MODES)
    if not (end_dt > start_dt):
        raise_error(ERR_INVALID_REQUEST, "end_time must be strictly after start_time")

    driver = core.must_find("drivers", driver_id, "driver not found")
    kart = core.must_find("karts", kart_id, "kart not found")

    # priority 6: state preconditions
    if driver["status"] != "ACTIVE":
        raise_error(ERR_DRIVER_NOT_ACTIVE, "driver is not ACTIVE")
    if kart["status"] != "AVAILABLE":
        raise_error(ERR_KART_UNAVAILABLE, "kart is not AVAILABLE")

    # priority 8: kart overlap against the kart's committed schedule
    for b in core.db["bookings"].values():
        if b["kart_id"] != kart["id"] or b["status"] not in _ACTIVE_BOOKING_STATES:
            continue
        b_start = parse_datetime(b["start_time"])
        b_end = parse_datetime(b["end_time"])
        if _windows_intersect(b_start, b_end, start_dt, end_dt):
            raise_error(ERR_BOOKING_OVERLAP, "window intersects an existing booking of this kart")

    # priority 9: aggregate track capacity ceiling
    intersecting = 0
    for b in core.db["bookings"].values():
        if b["status"] not in _ACTIVE_BOOKING_STATES:
            continue
        b_start = parse_datetime(b["start_time"])
        b_end = parse_datetime(b["end_time"])
        if _windows_intersect(b_start, b_end, start_dt, end_dt):
            intersecting += 1
    if intersecting >= core.TRACK_CAPACITY_KARTS:
        raise_error(ERR_TRACK_CAPACITY_EXCEEDED, "track capacity reached for this window")

    booking = core.create_record("bookings", {
        "driver_id": driver["id"],
        "kart_id": kart["id"],
        "start_time": start_raw,
        "end_time": end_raw,
        "pricing_mode": pricing_mode,
        "status": "RESERVED",
        "minutes_used": None,
        "fee_cents": None,
    })
    return success_object(core.serialize_booking(booking), 201)


@bp.get("/practice-bookings")
def list_bookings():
    authorized(ANY_ROLE)
    driver_id = request.args.get("driver_id")
    kart_id = request.args.get("kart_id")
    items = list(core.db["bookings"].values())
    if driver_id is not None:
        items = [b for b in items if b["driver_id"] == driver_id]
    if kart_id is not None:
        items = [b for b in items if b["kart_id"] == kart_id]
    items = core.list_sorted(items)
    page, total, limit, offset = core.paginate(items)
    return success_list([core.serialize_booking(b) for b in page], total, limit, offset)


@bp.get("/practice-bookings/<booking_id>")
def get_booking(booking_id):
    authorized(ANY_ROLE)
    booking = core.must_find("bookings", booking_id, "booking not found")
    return success_object(core.serialize_booking(booking))


def _load_own_booking(caller, booking_id, allow_admin=False):
    """Priority 2 ownership (Driver callers only), then priority 4 existence."""
    booking = core.find("bookings", booking_id)
    if booking is not None and not (allow_admin and caller.role == "LeagueAdmin"):
        check_driver_ownership(caller, booking["driver_id"])
    if booking is None:
        raise_error(ERR_NOT_FOUND, "booking not found")
    return booking


@bp.post("/practice-bookings/<booking_id>/check-in")
def check_in(booking_id):
    caller = authorized(["Driver"])
    booking = _load_own_booking(caller, booking_id)
    if booking["status"] != "RESERVED":
        raise_error(ERR_INVALID_STATE, "booking is not RESERVED")
    booking["status"] = "CHECKED_IN"
    core.touch(booking)
    return success_object(core.serialize_booking(booking))


@bp.post("/practice-bookings/<booking_id>/check-out")
def check_out(booking_id):
    caller = authorized(["Driver"])
    booking = _load_own_booking(caller, booking_id)
    if booking["status"] != "CHECKED_IN":
        raise_error(ERR_INVALID_STATE, "booking is not CHECKED_IN")
    start_dt = parse_datetime(booking["start_time"])
    end_dt = parse_datetime(booking["end_time"])
    minutes = whole_minutes(start_dt, end_dt)
    if booking["pricing_mode"] == "FLAT":
        fee = FLAT_SESSION_FEE_CENTS
    else:
        # round half-up to whole cents once per booking, at check-out (PRD 3.8)
        fee = metered_fee_cents(minutes)
    booking["status"] = "COMPLETED"
    booking["minutes_used"] = minutes
    booking["fee_cents"] = fee
    core.touch(booking)
    return success_object(core.serialize_booking(booking))


@bp.post("/practice-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    caller = authorized(["LeagueAdmin", "Driver"])
    booking = _load_own_booking(caller, booking_id, allow_admin=True)
    if booking["status"] != "RESERVED":
        raise_error(ERR_INVALID_STATE, "booking is not RESERVED")
    booking["status"] = "CANCELLED"
    core.touch(booking)
    return success_object(core.serialize_booking(booking))
