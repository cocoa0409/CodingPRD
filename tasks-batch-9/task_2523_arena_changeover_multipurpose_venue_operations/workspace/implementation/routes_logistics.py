"""The logistics layer: dock windows and labor calls."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import serial
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from routes_booking import get_booking
from store import db, now_logical, ordered, stamp_new, touch

bp = Blueprint("logistics", __name__)

PURPOSES = ("LOAD_IN", "LOAD_OUT")
CRAFTS = ("STAGEHAND", "RIGGER", "ICE_TECH", "ELECTRICIAN", "CONVERSION_CREW")
DOCK_BOOKING_STATES = ("HELD", "CHALLENGED", "CONFIRMED")


def get_reservation(reservation_id):
    reservation = db.docks.get(reservation_id)
    if reservation is None:
        raise ApiError("ERR_DOCK_RESERVATION_NOT_FOUND")
    return reservation


def get_call(call_id):
    call = db.labor_calls.get(call_id)
    if call is None:
        raise ApiError("ERR_LABOR_CALL_NOT_FOUND")
    return call


# --- dock windows ----------------------------------------------------------
@bp.post("/event-bookings/<booking_id>/dock-slot-reservations")
def reserve_dock(booking_id):
    v.auth(("ChangeoverSupervisor", "LaborCoordinator"))
    payload = v.body()
    # Ladder 5: shape. The dock-number range itself is a rank-16 domain check,
    # so only its integer type is validated here.
    dock_number = v.plain_int(payload, "dock_number")
    purpose = v.req_enum(payload, "purpose", PURPOSES)
    start = v.req_dt(payload, "window_start_utc")
    end = v.req_dt(payload, "window_end_utc")
    if end <= start:
        v.bad("window_end_utc must be strictly after window_start_utc.")
    truck_count = v.req_int(payload, "truck_count", 1, 60)

    booking = get_booking(booking_id)
    venue = db.venues.get(booking["venue_id"])
    # Ladder 9: from-state legality.
    if booking["status"] not in DOCK_BOOKING_STATES:
        raise ApiError("ERR_INVALID_BOOKING_STATE")

    buffer_minutes = int(venue["dock_buffer_minutes"]) if venue is not None else 0
    buffer_delta = timedelta(minutes=buffer_minutes)
    # Ladder 15: the buffered collision test runs before the range test.
    for peer in db.docks.values():
        if peer["status"] != "RESERVED" or int(peer["dock_number"]) != int(dock_number):
            continue
        peer_booking = db.bookings.get(peer["booking_id"])
        if peer_booking is None or peer_booking["venue_id"] != booking["venue_id"]:
            continue
        if start < peer["window_end_utc"] + buffer_delta \
                and peer["window_start_utc"] < end + buffer_delta:
            raise ApiError("ERR_DOCK_WINDOW_CONFLICT")
    # Ladder 16: the dock number must address a real dock on this arena.
    if venue is None or dock_number < 1 or dock_number > int(venue["dock_count"]):
        raise ApiError("ERR_DOCK_NUMBER_INVALID")

    row = {
        "booking_id": booking["id"],
        "dock_number": dock_number,
        "purpose": purpose,
        "window_start_utc": start,
        "window_end_utc": end,
        "truck_count": truck_count,
        "status": "RESERVED",
        "release_reason": None,
    }
    stamp_new(row)
    db.docks[row["id"]] = row
    return created(serial.dock(row))


@bp.get("/event-bookings/<booking_id>/dock-slot-reservations")
def list_dock_reservations(booking_id):
    v.auth(v.ALL_ROLES)
    limit, offset = v.pagination()
    booking = get_booking(booking_id)
    matched = [d for d in db.docks.values() if d["booking_id"] == booking["id"]]
    for field in ("purpose", "status"):
        value = v.filter_arg(field)
        if value is not None:
            matched = [d for d in matched if d[field] == value]
    matched = ordered(matched)
    page, total = v.paginate(matched, limit, offset)
    return ok_list([serial.dock(d) for d in page], limit, offset, total)


@bp.post("/dock-slot-reservations/<reservation_id>/cancel")
def cancel_dock(reservation_id):
    v.auth(("ChangeoverSupervisor", "LaborCoordinator"))
    reservation = get_reservation(reservation_id)
    # Ladder 9: from-state legality.
    if reservation["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_DOCK_RESERVATION_STATE")
    reservation["status"] = "RELEASED"
    reservation["release_reason"] = "OPERATOR_CANCEL"
    touch(reservation)
    return ok(serial.dock(reservation))


# --- labor calls -----------------------------------------------------------
@bp.post("/labor-calls")
def create_labor_call():
    v.auth(("LaborCoordinator",))
    payload = v.body()
    # Ladder 5: shape.
    craft = v.req_enum(payload, "craft", CRAFTS)
    headcount = v.req_int(payload, "headcount", 1, 200)
    start = v.req_dt(payload, "call_start_utc")
    end = v.req_dt(payload, "call_end_utc")
    if end <= start:
        v.bad("call_end_utc must be strictly after call_start_utc.")
    guaranteed_hours = v.opt_num(payload, "guaranteed_hours", 4, 0, 12)
    order_id = v.opt_id(payload, "changeover_order_id")
    booking_id = v.opt_id(payload, "booking_id")

    # Ladder 6: labor call scope exclusivity.
    if (order_id is None) == (booking_id is None):
        raise ApiError("ERR_LABOR_CALL_SCOPE_INVALID")

    # Ladder 7: existence, body identifiers in declaration order.
    order = None
    booking = None
    if order_id is not None:
        order = db.orders.get(order_id)
        if order is None:
            raise ApiError("ERR_CHANGEOVER_ORDER_NOT_FOUND")
    if booking_id is not None:
        booking = get_booking(booking_id)

    # Ladder 9: from-state legality on whichever scope was named.
    if order is not None and order["status"] in calc.TERMINAL_ORDER_STATES:
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if booking is not None and booking["status"] not in DOCK_BOOKING_STATES:
        raise ApiError("ERR_INVALID_BOOKING_STATE")

    venue = None
    if order is not None:
        venue = db.venues.get(order["venue_id"])
    elif booking is not None:
        venue = db.venues.get(booking["venue_id"])

    row = {
        "changeover_order_id": order["id"] if order is not None else None,
        "booking_id": booking["id"] if booking is not None else None,
        "craft": craft,
        "headcount": headcount,
        "call_start_utc": start,
        "call_end_utc": end,
        "guaranteed_hours": guaranteed_hours,
        "actual_hours": None,
        "overnight": calc.overnight_shift_flag(start, venue) if venue is not None else False,
        "status": "CALLED",
        "settled_cost_cents": None,
        "cancellation_fee_cents": 0,
    }
    row["estimated_cost_cents"] = calc.labor_call_cost_cents(row, "ESTIMATED")
    stamp_new(row)
    db.labor_calls[row["id"]] = row
    return created(serial.labor_call(row))


@bp.get("/labor-calls/<call_id>")
def read_labor_call(call_id):
    v.auth(v.ALL_ROLES)
    return ok(serial.labor_call(get_call(call_id)))


@bp.get("/labor-calls")
def list_labor_calls():
    v.auth(v.ALL_ROLES)
    limit, offset = v.pagination()
    matched = list(db.labor_calls.values())
    for field in ("changeover_order_id", "booking_id", "craft", "status"):
        value = v.filter_arg(field)
        if value is not None:
            matched = [c for c in matched if c[field] == value]
    matched = ordered(matched)
    page, total = v.paginate(matched, limit, offset)
    return ok_list([serial.labor_call(c) for c in page], limit, offset, total)


@bp.post("/labor-calls/<call_id>/close")
def close_labor_call(call_id):
    v.auth(("LaborCoordinator",))
    payload = v.body()
    actual_hours = v.req_num(payload, "actual_hours", 0, 24)
    call = get_call(call_id)
    # Ladder 9: the call itself, then the turnaround it is scoped to.
    if call["status"] != "CALLED":
        raise ApiError("ERR_INVALID_LABOR_CALL_STATE")
    if call["changeover_order_id"] is not None:
        order = db.orders.get(call["changeover_order_id"])
        if order is None or order["status"] not in ("READY_FOR_SIGNOFF", "SIGNED_OFF"):
            raise ApiError("ERR_INVALID_ORDER_STATE")

    call["actual_hours"] = actual_hours
    call["status"] = "WORKED"
    call["settled_cost_cents"] = calc.labor_call_cost_cents(call, "SETTLED")
    touch(call)
    return ok(serial.labor_call(call))


@bp.post("/labor-calls/<call_id>/cancel")
def cancel_labor_call(call_id):
    v.auth(("LaborCoordinator",))
    call = get_call(call_id)
    # Ladder 9: from-state legality.
    if call["status"] != "CALLED":
        raise ApiError("ERR_INVALID_LABOR_CALL_STATE")
    cascade.cancel_labor_call(call)
    return ok(serial.labor_call(call))
