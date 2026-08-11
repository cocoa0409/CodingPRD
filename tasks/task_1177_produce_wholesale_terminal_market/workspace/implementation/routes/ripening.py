"""RipeningRoom and RipeningBooking routes — ethylene safety, 2h buffer
overlap, aggregate pallet capacity, booking lifecycle."""

from datetime import timedelta

from flask import Blueprint

from db import store
from errors import (
    raise_error,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_ETHYLENE_CONFLICT,
    ERR_ROOM_OVERLAP,
    ERR_ROOM_CAPACITY,
    ERR_LOT_NOT_ACCEPTED,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.domain import (
    get_json_body,
    require_fields,
    req_string,
    req_positive_int,
    req_bool,
    req_datetime,
    is_str,
    lookup,
    stamp_new,
    touch,
    paginate,
    sorted_by_created,
    clock_now,
)

bp = Blueprint("ripening", __name__)

BUFFER = timedelta(hours=2)
ACTIVE_BOOKING_STATUSES = {"SCHEDULED", "IN_PROCESS"}


@bp.post("/market/ripening-rooms")
def create_room():
    require_roles(["MarketAdmin"])
    body = get_json_body()
    require_fields(body, ["name", "capacity_pallets", "ethylene_capable"])
    room = stamp_new(
        {
            "name": req_string(body, "name"),
            "capacity_pallets": req_positive_int(body, "capacity_pallets"),
            "ethylene_capable": req_bool(body, "ethylene_capable"),
        }
    )
    store.ripening_rooms[room["id"]] = room
    return success_object(room, 201)


@bp.get("/market/ripening-rooms/<room_id>")
def get_room(room_id):
    require_roles(ALL_ROLES)
    room = lookup(store.ripening_rooms, room_id, "RipeningRoom")
    return success_object(room, 200)


@bp.get("/market/ripening-rooms/<room_id>/ripening-bookings")
def list_room_bookings(room_id):
    require_roles(ALL_ROLES)
    lookup(store.ripening_rooms, room_id, "RipeningRoom")
    items = [b for b in store.ripening_bookings.values() if b["room_id"] == room_id]
    items = sorted_by_created(items)
    page, pagination = paginate(items)
    return success_list(page, pagination, 200)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Strict half-open [start, end) intersection."""
    return a_start < b_end and b_start < a_end


@bp.post("/market/ripening-bookings")
def create_booking():
    require_roles(["Receiver"])
    body = get_json_body()
    require_fields(
        body,
        [
            "room_id",
            "purchase_lot_id",
            "pallet_count",
            "start_time",
            "end_time",
            "ethylene_enabled",
            "target_stage",
        ],
    )
    room_id = body.get("room_id")
    purchase_lot_id = body.get("purchase_lot_id")
    if not is_str(room_id):
        raise_error(ERR_VALIDATION, "room_id must be a string")
    if not is_str(purchase_lot_id):
        raise_error(ERR_VALIDATION, "purchase_lot_id must be a string")
    pallet_count = req_positive_int(body, "pallet_count")
    start_time = req_datetime(body, "start_time")
    end_time = req_datetime(body, "end_time")
    ethylene_enabled = req_bool(body, "ethylene_enabled")
    target_stage = req_string(body, "target_stage")
    if end_time <= start_time:
        raise_error(ERR_VALIDATION, "end_time must be after start_time")

    # FK existence, body field order (priority 4)
    room = lookup(store.ripening_rooms, room_id, "RipeningRoom")
    lot = lookup(store.purchase_lots, purchase_lot_id, "PurchaseLot")

    # Lot must not be REJECTED or CLOSED (state legality)
    if lot["status"] in {"REJECTED", "CLOSED"}:
        raise_error(
            ERR_INVALID_STATE,
            f"Lot status {lot['status']} cannot be scheduled for ripening",
        )

    new_commodity = store.commodities.get(lot["commodity_id"])
    new_is_sensitive = (
        new_commodity is not None and new_commodity["ethylene_class"] == "SENSITIVE"
    )

    active = [
        b
        for b in store.ripening_bookings.values()
        if b["room_id"] == room_id and b["status"] in ACTIVE_BOOKING_STATUSES
    ]

    # Priority 7 safety: ethylene conflict uses UNINFLATED interval overlap.
    for b in active:
        b_start = _parse_iso(b["start_time"])
        b_end = _parse_iso(b["end_time"])
        if not _intervals_overlap(start_time, end_time, b_start, b_end):
            continue
        b_lot = store.purchase_lots.get(b["purchase_lot_id"])
        b_commodity = (
            store.commodities.get(b_lot["commodity_id"]) if b_lot else None
        )
        b_is_sensitive = (
            b_commodity is not None and b_commodity["ethylene_class"] == "SENSITIVE"
        )
        if (ethylene_enabled and b_is_sensitive) or (
            new_is_sensitive and b["ethylene_enabled"]
        ):
            raise_error(
                ERR_ETHYLENE_CONFLICT,
                "Ethylene injection conflicts with a SENSITIVE-commodity lot",
            )

    # Priority 8 temporal: overlap against 2h-buffer-inflated active intervals.
    for b in active:
        b_start = _parse_iso(b["start_time"]) - BUFFER
        b_end = _parse_iso(b["end_time"]) + BUFFER
        if _intervals_overlap(start_time, end_time, b_start, b_end):
            raise_error(
                ERR_ROOM_OVERLAP,
                "Booking interval intersects an active booking's buffer-inflated interval",
            )

    # Priority 9 domain: aggregate pallet capacity over overlapping actives
    # (uninflated overlap; equality allowed).
    pallet_sum = 0
    for b in active:
        b_start = _parse_iso(b["start_time"])
        b_end = _parse_iso(b["end_time"])
        if _intervals_overlap(start_time, end_time, b_start, b_end):
            pallet_sum += b["pallet_count"]
    if pallet_sum + pallet_count > room["capacity_pallets"]:
        raise_error(
            ERR_ROOM_CAPACITY,
            f"Room capacity {room['capacity_pallets']} pallets exceeded",
        )

    booking = stamp_new(
        {
            "room_id": room_id,
            "purchase_lot_id": purchase_lot_id,
            "pallet_count": pallet_count,
            "start_time": _fmt(start_time),
            "end_time": _fmt(end_time),
            "ethylene_enabled": ethylene_enabled,
            "target_stage": target_stage,
            "status": "SCHEDULED",
        }
    )
    store.ripening_bookings[booking["id"]] = booking
    return success_object(booking, 201)


def _parse_iso(s):
    from services.domain import parse_datetime

    return parse_datetime(s, "datetime")


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.get("/market/purchase-lots/<lot_id>/ripening-bookings")
def list_lot_bookings(lot_id):
    require_roles(ALL_ROLES)
    lookup(store.purchase_lots, lot_id, "PurchaseLot")
    items = [
        b for b in store.ripening_bookings.values() if b["purchase_lot_id"] == lot_id
    ]
    items = sorted_by_created(items)
    page, pagination = paginate(items)
    return success_list(page, pagination, 200)


@bp.post("/market/ripening-bookings/<booking_id>/start")
def start_booking(booking_id):
    require_roles(["Receiver"])
    booking = lookup(store.ripening_bookings, booking_id, "RipeningBooking")
    if booking["status"] != "SCHEDULED":
        raise_error(
            ERR_INVALID_STATE,
            f"Booking must be SCHEDULED to start; current status {booking['status']}",
        )
    lot = lookup(store.purchase_lots, booking["purchase_lot_id"], "PurchaseLot")
    if lot["status"] != "ACCEPTED":
        raise_error(
            ERR_LOT_NOT_ACCEPTED,
            f"Lot must be ACCEPTED to start booking; current status {lot['status']}",
        )
    now = clock_now()
    start_time = _parse_iso(booking["start_time"])
    end_time = _parse_iso(booking["end_time"])
    if not (start_time <= now < end_time):
        raise_error(
            ERR_INVALID_STATE,
            "Logical clock is outside the booking's [start_time, end_time) window",
        )
    booking["status"] = "IN_PROCESS"
    touch(booking)
    return success_object(booking, 200)


@bp.post("/market/ripening-bookings/<booking_id>/complete")
def complete_booking(booking_id):
    require_roles(["Receiver"])
    booking = lookup(store.ripening_bookings, booking_id, "RipeningBooking")
    if booking["status"] != "IN_PROCESS":
        raise_error(
            ERR_INVALID_STATE,
            f"Booking must be IN_PROCESS to complete; current status {booking['status']}",
        )
    booking["status"] = "COMPLETED"
    touch(booking)
    return success_object(booking, 200)


@bp.post("/market/ripening-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    require_roles(["Receiver"])
    booking = lookup(store.ripening_bookings, booking_id, "RipeningBooking")
    if booking["status"] != "SCHEDULED":
        raise_error(
            ERR_INVALID_STATE,
            f"Booking must be SCHEDULED to cancel; current status {booking['status']}",
        )
    booking["status"] = "CANCELLED"
    touch(booking)
    return success_object(booking, 200)
