"""Booking helpers: catalog computed counts, unit selection, overlap checks.

PRD §2.8 (computed counts), §3.4 (unit selector, double-booking, closed-interval
adjacency), §3.5 (truck window half-open + buffer collision).
"""
from datetime import timedelta

from db import DB

from .common import parse_date, parse_datetime, sort_by_created

# Reservation states that still hold the unit's future interval (active bookings).
# Per PRD §3.4 the temporal-overlap check considers "active reservation or
# agreement on the same EquipmentUnit". CANCELLED frees the interval; FULFILLED
# means the agreement closed and the rental is over. The agreement covers the
# live ON_RENT / RETURNED_PENDING_INSPECTION window.
ACTIVE_RESERVATION_STATES = {"CONFIRMED", "DISPATCHED_DELIVERY", "PICKED_UP", "ON_RENT"}


# --------------------------------------------------------------------------
# Catalog computed counts (PRD §2.8)
# --------------------------------------------------------------------------

def unit_count(catalog_item_id):
    return sum(1 for u in DB.equipment_units.values()
               if u["catalog_item_id"] == catalog_item_id)


def available_unit_count(catalog_item_id):
    return sum(1 for u in DB.equipment_units.values()
               if u["catalog_item_id"] == catalog_item_id
               and u["availability_state"] == "AVAILABLE")


def catalog_view(item):
    out = dict(item)
    out["unit_count"] = unit_count(item["id"])
    out["available_unit_count"] = available_unit_count(item["id"])
    return out


# --------------------------------------------------------------------------
# Unit interval overlap (PRD §3.4 — closed interval, adjacency is NOT overlap)
# --------------------------------------------------------------------------

def _intervals_overlap_closed(s1, e1, s2, e2):
    """Closed-interval overlap with adjacency allowed (PRD §3.4).

    [s1,e1] and [s2,e2] are inclusive rental-day ranges. "One booking ending on
    the very day another begins is allowed" — i.e. a single shared day that is
    the end of one range and the start of the other is NOT an overlap. Any other
    shared time is an overlap.

    A single shared day that is the end of one range and the start of the other
    is treated as adjacency (allowed). Any larger shared span is an overlap.
    """
    lo = max(s1, s2)
    hi = min(e1, e2)
    if lo > hi:
        return False  # disjoint
    if lo == hi:
        # Exactly one shared day. Allowed iff it is an adjacency boundary: the
        # end of one range and the start of the other.
        adjacency = (hi == e1 and lo == s2) or (hi == e2 and lo == s1)
        return not adjacency
    return True  # two or more shared days -> overlap


def unit_has_overlapping_booking(unit_id, start_str, end_str, exclude_reservation_id=None):
    """True if any active reservation/agreement on the unit overlaps [start,end]."""
    s = parse_date(start_str)
    e = parse_date(end_str)
    for r in DB.reservations.values():
        if r["id"] == exclude_reservation_id:
            continue
        if r["equipment_unit_id"] != unit_id:
            continue
        if r["reservation_state"] not in ACTIVE_RESERVATION_STATES:
            continue
        rs = parse_date(r["rental_start_date"])
        re = parse_date(r["rental_end_date"])
        if _intervals_overlap_closed(s, e, rs, re):
            return True
    return False


def select_unit(catalog_item_id, start_str, end_str):
    """Selector policy (PRD §3.4): among AVAILABLE units of the item with no
    overlapping booking for the interval, take the earliest by created_at ASC.
    Returns the unit record or None when the candidate pool is empty."""
    candidates = [u for u in DB.equipment_units.values()
                  if u["catalog_item_id"] == catalog_item_id
                  and u["availability_state"] == "AVAILABLE"]
    candidates = sort_by_created(candidates)
    for u in candidates:
        if not unit_has_overlapping_booking(u["id"], start_str, end_str):
            return u
    return None


# --------------------------------------------------------------------------
# Truck delivery window collision (PRD §3.5 — half-open + buffer)
# --------------------------------------------------------------------------

# Reservation states that hold a live truck delivery window. A window is assigned
# at dispatch (DISPATCHED_DELIVERY) and the reservation then moves to ON_RENT
# while still occupying that truck slot. SCAFFOLD §1.2 precondition references
# "any other DISPATCHED_DELIVERY/ON_RENT reservation's window on the same truck".
TRUCK_WINDOW_STATES = {"DISPATCHED_DELIVERY", "ON_RENT"}


def truck_window_collides(truck, new_start_str, new_end_str, buffer_minutes,
                          exclude_reservation_id=None):
    """Half-open [start, end) collision padded by buffer_minutes on each side.

    The requested window expanded by buffer on both sides must not collide with
    any other assigned window on the same truck. Adjacency within the buffer is a
    collision."""
    new_start = parse_datetime(new_start_str)
    new_end = parse_datetime(new_end_str)
    buf = timedelta(minutes=buffer_minutes)
    pad_start = new_start - buf
    pad_end = new_end + buf

    for r in DB.reservations.values():
        if r["id"] == exclude_reservation_id:
            continue
        if r.get("delivery_truck_id") != truck["id"]:
            continue
        if r["reservation_state"] not in TRUCK_WINDOW_STATES:
            continue
        if not r.get("delivery_window_start") or not r.get("delivery_window_end"):
            continue
        other_start = parse_datetime(r["delivery_window_start"])
        other_end = parse_datetime(r["delivery_window_end"])
        # Half-open overlap: two intervals [a,b) and [c,d) overlap iff a < d and
        # c < b. The padded request is [pad_start, pad_end); the existing window
        # is [other_start, other_end). "adjacency within the buffer is a
        # collision" is captured by padding the request, so touching the padded
        # boundary (pad_end == other_start) is NOT a collision (half-open), but
        # any window falling inside the buffer gap is.
        if pad_start < other_end and other_start < pad_end:
            return True
    return False
