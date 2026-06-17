"""Booking geometry & policy resolution helpers (PRD §3.3/§3.4/§3.9/§3.10)."""
from __future__ import annotations

from typing import Dict, Optional, List

import db


# Default capacity-policy knobs when a floor has no explicit policy (PRD §3.3).
DEFAULT_MAX_ACTIVE = 1
DEFAULT_GRACE_MINUTES = 30
DEFAULT_ENFORCE_TEAM_ZONING = True

NON_TERMINAL_OCCUPANCY = ("BOOKED", "CHECKED_IN")
# A VisitorPass holds/locks the seat window while in these states (PRD §3.10).
# REQUESTED holds a tentative window; APPROVED/CHECKED_IN lock it.
ACTIVE_VISITOR_PASS = ("REQUESTED", "APPROVED", "CHECKED_IN")


def floor_of_seat(seat: Dict) -> Optional[Dict]:
    neigh = db.neighborhoods.get(seat["neighborhood_id"])
    if neigh is None:
        return None
    return db.floors.get(neigh["floor_id"])


def neighborhood_of_seat(seat: Dict) -> Optional[Dict]:
    return db.neighborhoods.get(seat["neighborhood_id"])


def floor_of_room(room: Dict) -> Optional[Dict]:
    return db.floors.get(room["floor_id"])


def policy_for_floor(floor_id: str) -> Dict:
    """Return the effective capacity policy for a floor: the stored policy if any,
    else the documented defaults (PRD §3.3)."""
    for p in db.capacity_policies.values():
        if p["floor_id"] == floor_id:
            return {
                "max_active_reservations_per_employee": p["max_active_reservations_per_employee"],
                "grace_minutes": p["grace_minutes"],
                "enforce_team_zoning": p["enforce_team_zoning"],
            }
    return {
        "max_active_reservations_per_employee": DEFAULT_MAX_ACTIVE,
        "grace_minutes": DEFAULT_GRACE_MINUTES,
        "enforce_team_zoning": DEFAULT_ENFORCE_TEAM_ZONING,
    }


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Half-open intervals [start, end): touching endpoints do NOT overlap."""
    return a_start < b_end and b_start < a_end


def seat_window_conflict(seat_id: str, booking_date: str, start: int, end: int,
                         exclude_reservation_id: Optional[str] = None,
                         exclude_pass_id: Optional[str] = None) -> bool:
    """True if [start,end) intersects a non-terminal reservation OR an active
    visitor pass on the same seat & date (PRD §3.4 / §3.10)."""
    for r in db.reservations.values():
        if r is None:
            continue
        if r["resource_type"] != "SEAT" or r["seat_id"] != seat_id:
            continue
        if r["booking_date"] != booking_date:
            continue
        if r["occupancy_status"] not in NON_TERMINAL_OCCUPANCY:
            continue
        if exclude_reservation_id is not None and r["id"] == exclude_reservation_id:
            continue
        if _overlaps(start, end, r["start_minute"], r["end_minute"]):
            return True
    for vp in db.visitor_passes.values():
        if vp["seat_id"] != seat_id:
            continue
        if vp["booking_date"] != booking_date:
            continue
        if vp["status"] not in ACTIVE_VISITOR_PASS:
            continue
        if exclude_pass_id is not None and vp["id"] == exclude_pass_id:
            continue
        if _overlaps(start, end, vp["start_minute"], vp["end_minute"]):
            return True
    return False


def room_window_conflict(room: Dict, booking_date: str, start: int, end: int) -> bool:
    """ROOM overlap with the room's turnover_buffer_minute appended AFTER the
    requested window (PRD §3.4). The new booking's effective span is
    [start, end + buffer); each existing booking's effective span is likewise
    [r.start, r.end + buffer)."""
    buffer = room["turnover_buffer_minute"]
    new_end_buffered = end + buffer
    for r in db.reservations.values():
        if r["resource_type"] != "ROOM" or r["room_id"] != room["id"]:
            continue
        if r["booking_date"] != booking_date:
            continue
        if r["occupancy_status"] not in NON_TERMINAL_OCCUPANCY:
            continue
        existing_end_buffered = r["end_minute"] + buffer
        if _overlaps(start, new_end_buffered, r["start_minute"], existing_end_buffered):
            return True
    return False


def count_active_reservations_for_employee(employee_id: str, floor_id: str,
                                           booking_date: str) -> int:
    """Count non-terminal (BOOKED/CHECKED_IN) reservations the employee holds on
    the given floor & date (PRD §3.4)."""
    count = 0
    for r in db.reservations.values():
        if r["employee_id"] != employee_id:
            continue
        if r["booking_date"] != booking_date:
            continue
        if r["occupancy_status"] not in NON_TERMINAL_OCCUPANCY:
            continue
        rf = floor_of_reservation(r)
        if rf is not None and rf["id"] == floor_id:
            count += 1
    return count


def floor_of_reservation(r: Dict) -> Optional[Dict]:
    if r["resource_type"] == "SEAT":
        seat = db.seats.get(r["seat_id"])
        if seat is None:
            return None
        return floor_of_seat(seat)
    room = db.rooms.get(r["room_id"])
    if room is None:
        return None
    return floor_of_room(room)
