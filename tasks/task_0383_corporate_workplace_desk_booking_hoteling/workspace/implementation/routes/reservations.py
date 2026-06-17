"""Reservation routes: create, fetch, list/filter, and lifecycle transitions.

Validation precedence for create (PRD §2.6 + §3.4, scaffold §1.4 priorities):
  1 auth (401) -> 2 role + ownership (403) -> 3 existence of FKs (404)
  -> 4 well-formed body (422) -> 5 target-selector mismatch (422)
  -> 6 outside workday (422) -> 8 resource not bookable (409)
  -> 9 booking suspended (409) -> 10 team zoning (409)
  -> 11 reservation limit (409) -> 12 seat double-booked (409)
  -> 13 room double-booked (409) -> 14 neighborhood capacity (409)
  -> 15 OCC stale version (412).
"""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_RESOURCE_TARGET_MISMATCH,
    ERR_OUTSIDE_WORKDAY,
    ERR_INVALID_STATE,
    ERR_RESOURCE_NOT_BOOKABLE,
    ERR_BOOKING_SUSPENDED,
    ERR_TEAM_ZONING_VIOLATION,
    ERR_RESERVATION_LIMIT_REACHED,
    ERR_SEAT_DOUBLE_BOOKED,
    ERR_ROOM_DOUBLE_BOOKED,
    ERR_NEIGHBORHOOD_CAPACITY_FULL,
    ERR_STALE_VERSION,
    ERR_AMENITY_LOCKED,
)
from middleware import require_role, current_user_id
from response import ok_object, ok_array
from routes._helpers import (
    parse_pagination, paginate, order_by_created, get_body,
    get_reservation, get_employee, get_seat, get_room,
)
from services.common import stamp_new, touch, public, public_list
from services import calculations as calc
from services import booking
from services import state_machines as sm

bp = Blueprint("reservations", __name__)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@bp.post("/workplace/reservations")
def create_reservation():
    require_role("Employee")  # priority 1 + 2 (role)
    body = get_body()

    # ---- priority 2 (ownership): supplied employee_id must equal X-User-ID ----
    # employee_id must be present & a string to compare; if absent/typeerror this
    # is a well-formedness issue (422). But ownership precedes existence, so we
    # compare the raw value when present.
    employee_id = body.get("employee_id")
    if employee_id is not None and isinstance(employee_id, str):
        if employee_id != current_user_id():
            raise APIError(ERR_FORBIDDEN, 403, "employee_id must equal acting X-User-ID")

    # ---- priority 3 (existence): body FKs in order ----
    # well-formedness of types overlaps; we resolve existence for present FKs.
    if employee_id is None or not isinstance(employee_id, str):
        raise APIError(ERR_INVALID_REQUEST, 422, "employee_id required")
    employee = db.employees.get(employee_id)
    if employee is None:
        raise APIError(ERR_NOT_FOUND, 404, "Employee not found")

    resource_type = body.get("resource_type")
    seat_id = body.get("seat_id")
    room_id = body.get("room_id")

    # Existence of referenced seat/room (only if a non-null id was supplied).
    seat = None
    room = None
    if seat_id is not None:
        if not isinstance(seat_id, str):
            raise APIError(ERR_INVALID_REQUEST, 422, "seat_id must be a string")
        seat = db.seats.get(seat_id)
        if seat is None:
            raise APIError(ERR_NOT_FOUND, 404, "Seat not found")
    if room_id is not None:
        if not isinstance(room_id, str):
            raise APIError(ERR_INVALID_REQUEST, 422, "room_id must be a string")
        room = db.rooms.get(room_id)
        if room is None:
            raise APIError(ERR_NOT_FOUND, 404, "Room not found")

    # ---- priority 4 (well-formed body) ----
    if resource_type not in ("SEAT", "ROOM"):
        raise APIError(ERR_INVALID_REQUEST, 422, "resource_type must be SEAT or ROOM")
    booking_date = body.get("booking_date")
    if not _is_iso_date(booking_date):
        raise APIError(ERR_INVALID_REQUEST, 422, "booking_date must be YYYY-MM-DD")
    start_minute = body.get("start_minute")
    end_minute = body.get("end_minute")
    if not _is_int(start_minute) or not _is_int(end_minute):
        raise APIError(ERR_INVALID_REQUEST, 422, "start_minute/end_minute must be integers")
    # optional version fields type-check
    expected_seat_version = body.get("expected_seat_version")
    expected_room_version = body.get("expected_room_version")
    if expected_seat_version is not None and not _is_int(expected_seat_version):
        raise APIError(ERR_INVALID_REQUEST, 422, "expected_seat_version must be an integer")
    if expected_room_version is not None and not _is_int(expected_room_version):
        raise APIError(ERR_INVALID_REQUEST, 422, "expected_room_version must be an integer")

    # ---- priority 5: exclusive selector ----
    if resource_type == "SEAT":
        if seat_id is None or room_id is not None:
            raise APIError(ERR_RESOURCE_TARGET_MISMATCH, 422,
                           "SEAT requires seat_id and null room_id")
    else:  # ROOM
        if room_id is None or seat_id is not None:
            raise APIError(ERR_RESOURCE_TARGET_MISMATCH, 422,
                           "ROOM requires room_id and null seat_id")

    # Resolve the floor for workday-window checks.
    if resource_type == "SEAT":
        floor = booking.floor_of_seat(seat)
    else:
        floor = booking.floor_of_room(room)
    if floor is None:
        # parent chain broken — treat as not found
        raise APIError(ERR_NOT_FOUND, 404, "Floor not found for resource")

    # ---- priority 6: outside workday ----
    if not (start_minute < end_minute):
        raise APIError(ERR_OUTSIDE_WORKDAY, 422, "start_minute must be < end_minute")
    if start_minute < floor["workday_start_minute"] or end_minute > floor["workday_end_minute"]:
        raise APIError(ERR_OUTSIDE_WORKDAY, 422, "window outside floor workday")

    # ---- priority 8: resource bookable (AVAILABLE) ----
    if resource_type == "SEAT":
        if seat["status"] != "AVAILABLE":
            raise APIError(ERR_RESOURCE_NOT_BOOKABLE, 409, "Seat not AVAILABLE")
    else:
        if room["status"] != "AVAILABLE":
            raise APIError(ERR_RESOURCE_NOT_BOOKABLE, 409, "Room not AVAILABLE")

    # ---- priority 9: booking privilege ACTIVE ----
    employee["strike_score"] = calc.compute_strike_score(employee)
    employee["booking_privilege"] = calc.derive_privilege(employee["strike_score"])
    if employee["booking_privilege"] == "SUSPENDED":
        raise APIError(ERR_BOOKING_SUSPENDED, 409, "Employee booking privilege SUSPENDED")

    policy = booking.policy_for_floor(floor["id"])

    # ---- priority 10: team zoning (SEAT only) ----
    if resource_type == "SEAT":
        neigh = booking.neighborhood_of_seat(seat)
        if policy["enforce_team_zoning"] and neigh is not None and neigh["team_code"] is not None:
            if employee["team_code"] != neigh["team_code"]:
                raise APIError(ERR_TEAM_ZONING_VIOLATION, 409, "Team zoning violation")

    # ---- priority 11: reservation limit ----
    active = booking.count_active_reservations_for_employee(
        employee["id"], floor["id"], booking_date)
    if active >= policy["max_active_reservations_per_employee"]:
        raise APIError(ERR_RESERVATION_LIMIT_REACHED, 409, "Reservation limit reached")

    # ---- priority 12/13: overlap ----
    if resource_type == "SEAT":
        if booking.seat_window_conflict(seat_id, booking_date, start_minute, end_minute):
            raise APIError(ERR_SEAT_DOUBLE_BOOKED, 409, "Seat double-booked")
    else:
        if booking.room_window_conflict(room, booking_date, start_minute, end_minute):
            raise APIError(ERR_ROOM_DOUBLE_BOOKED, 409, "Room double-booked")

    # ---- priority 14: neighborhood capacity (SEAT only) ----
    if resource_type == "SEAT":
        neigh = booking.neighborhood_of_seat(seat)
        if neigh is not None and not calc.capacity_allows(neigh, booking_date, seat_id):
            raise APIError(ERR_NEIGHBORHOOD_CAPACITY_FULL, 409, "Neighborhood capacity full")

    # ---- priority 15: OCC stale version ----
    if resource_type == "SEAT":
        if expected_seat_version is not None and expected_seat_version != seat["version"]:
            raise APIError(ERR_STALE_VERSION, 412, "Stale seat version")
    else:
        if expected_room_version is not None and expected_room_version != room["version"]:
            raise APIError(ERR_STALE_VERSION, 412, "Stale room version")

    # ---- commit ----
    checkin_deadline = start_minute + policy["grace_minutes"]
    reservation = {
        "employee_id": employee["id"],
        "resource_type": resource_type,
        "seat_id": seat_id if resource_type == "SEAT" else None,
        "room_id": room_id if resource_type == "ROOM" else None,
        "booking_date": booking_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "occupancy_status": "BOOKED",
        "billing_status": "NONE",
        "provisional_chargeback_cents": 0,
        "final_chargeback_cents": 0,
        "checkin_deadline_minute": checkin_deadline,
        "occupied_minutes": 0,
    }
    stamp_new(reservation)
    db.reservations[reservation["id"]] = reservation

    # advance the booked seat/room version by 1 (PRD §2.10 / §3.4)
    if resource_type == "SEAT":
        touch(seat)
    else:
        touch(room)

    return ok_object(public(reservation), 201)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@bp.get("/workplace/reservations/<rid>")
def get_reservation_ep(rid):
    require_role("FacilityManager", "Analyst", "Employee")
    r = get_reservation(rid)
    _read_ownership_guard(r)
    return ok_object(public(r))


@bp.get("/workplace/reservations")
def list_reservations():
    require_role("FacilityManager", "Analyst", "Employee")
    limit, offset = parse_pagination()
    role = g.user_role
    uid = current_user_id()
    items = list(db.reservations.values())

    # Employee may only see own reservations (entity_backed ownership read).
    if role == "Employee":
        items = [r for r in items if r["employee_id"] == uid]

    # optional filters
    f_emp = request.args.get("employee_id")
    f_seat = request.args.get("seat_id")
    f_room = request.args.get("room_id")
    f_date = request.args.get("booking_date")
    f_occ = request.args.get("occupancy_status")
    if f_emp is not None:
        items = [r for r in items if r["employee_id"] == f_emp]
    if f_seat is not None:
        items = [r for r in items if r["seat_id"] == f_seat]
    if f_room is not None:
        items = [r for r in items if r["room_id"] == f_room]
    if f_date is not None:
        items = [r for r in items if r["booking_date"] == f_date]
    if f_occ is not None:
        items = [r for r in items if r["occupancy_status"] == f_occ]

    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(public_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------

@bp.post("/workplace/reservations/<rid>/check-in")
def check_in(rid):
    require_role("Employee")
    r = get_reservation(rid)
    _owner_guard(r)
    if r["occupancy_status"] != "BOOKED":
        raise APIError(ERR_INVALID_STATE, 409, "Reservation not BOOKED")
    clock_minute = _require_clock_minute()
    if clock_minute > r["checkin_deadline_minute"]:
        raise APIError(ERR_INVALID_STATE, 409, "Grace window expired")
    # the booked seat/room must still be AVAILABLE
    if not _resource_available(r):
        raise APIError(ERR_RESOURCE_NOT_BOOKABLE, 409, "Resource no longer AVAILABLE")
    employee = db.employees[r["employee_id"]]
    sm.reservation_check_in(r, employee, clock_minute)
    return ok_object(public(r))


@bp.post("/workplace/reservations/<rid>/complete")
def complete(rid):
    require_role("Employee")
    r = get_reservation(rid)
    _owner_guard(r)
    if r["occupancy_status"] != "CHECKED_IN":
        raise APIError(ERR_INVALID_STATE, 409, "Reservation not CHECKED_IN")
    sm.reservation_complete(r)
    return ok_object(public(r))


@bp.post("/workplace/reservations/<rid>/cancel")
def cancel(rid):
    require_role("Employee")
    r = get_reservation(rid)
    _owner_guard(r)
    if r["occupancy_status"] not in ("BOOKED", "CHECKED_IN"):
        raise APIError(ERR_INVALID_STATE, 409, "Reservation not cancellable")
    sm.reservation_cancel(r)
    return ok_object(public(r))


@bp.post("/workplace/reservations/<rid>/release")
def release(rid):
    require_role("FacilityManager")
    r = get_reservation(rid)
    if r["occupancy_status"] != "BOOKED":
        raise APIError(ERR_INVALID_STATE, 409, "Reservation not BOOKED")
    clock_minute = _require_clock_minute()
    if not (clock_minute > r["checkin_deadline_minute"]):
        raise APIError(ERR_INVALID_STATE, 409, "Grace window not expired")
    employee = db.employees[r["employee_id"]]
    sm.reservation_release(r, employee)
    return ok_object(public(r))


# ---------------------------------------------------------------------------
# Reservation sub-collections
# ---------------------------------------------------------------------------

@bp.get("/workplace/reservations/<rid>/check-ins")
def list_check_ins(rid):
    require_role("FacilityManager", "Analyst", "Employee")
    r = get_reservation(rid)
    _read_ownership_guard(r)
    items = [c for c in db.checkins.values() if c["reservation_id"] == r["id"]]
    items = order_by_created(items)
    # check-ins endpoint has no pagination params in scaffold; return all
    return ok_array(public_list(items), len(items), 0, len(items))


@bp.get("/workplace/reservations/<rid>/no-show-events")
def list_reservation_no_show(rid):
    require_role("FacilityManager", "Analyst")
    r = get_reservation(rid)
    limit, offset = parse_pagination()
    items = [ev for ev in db.no_show_events.values() if ev["reservation_id"] == r["id"]]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(public_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _owner_guard(r):
    """Employee acting on a reservation must own it (PRD §2.1)."""
    if g.user_role == "Employee" and r["employee_id"] != current_user_id():
        raise APIError(ERR_FORBIDDEN, 403, "Caller does not own this reservation")


def _read_ownership_guard(r):
    if g.user_role == "Employee" and r["employee_id"] != current_user_id():
        raise APIError(ERR_FORBIDDEN, 403, "Caller does not own this reservation")


def _resource_available(r) -> bool:
    if r["resource_type"] == "SEAT":
        seat = db.seats.get(r["seat_id"])
        return seat is not None and seat["status"] == "AVAILABLE"
    room = db.rooms.get(r["room_id"])
    return room is not None and room["status"] == "AVAILABLE"


def _require_clock_minute() -> int:
    cm = db.clock.get("current_minute")
    if cm is None:
        raise APIError(ERR_INVALID_STATE, 409, "Logical clock not set")
    return cm


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_iso_date(v) -> bool:
    if not isinstance(v, str) or len(v) != 10 or v[4] != "-" or v[7] != "-":
        return False
    y, m, d = v[:4], v[5:7], v[8:10]
    if not (y.isdigit() and m.isdigit() and d.isdigit()):
        return False
    mi, di = int(m), int(d)
    return 1 <= mi <= 12 and 1 <= di <= 31
