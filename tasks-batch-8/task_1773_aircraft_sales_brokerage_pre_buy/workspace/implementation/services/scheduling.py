"""Booking window conflict rules (PRD 3.7, validation priority 7).

Facility rule (evaluated FIRST): reject when any other REQUESTED/CONFIRMED
booking at the same facility has a window that, expanded by the facility's
turnaround_buffer_minutes on both sides, intersects the requested half-open
window [start_at, end_at). A gap of exactly buffer minutes is sufficient.

Aircraft rule (SECOND): reject when any other REQUESTED/CONFIRMED booking for
the same transaction's listing strictly overlaps the requested window;
half-open semantics mean adjacency (end_at == start_at) is allowed.
"""
from datetime import timedelta

import db as dbmod

ACTIVE_BOOKING_STATES = ("REQUESTED", "CONFIRMED")


def facility_slot_conflict(facility, start, end):
    buffer = timedelta(minutes=facility["turnaround_buffer_minutes"])
    for other in dbmod.db["bookings"].values():
        if other["status"] not in ACTIVE_BOOKING_STATES:
            continue
        if other["facility_id"] != facility["id"]:
            continue
        other_start = other["_start_dt"]
        other_end = other["_end_dt"]
        # No conflict when the requested window clears the expanded window.
        if start >= other_end + buffer or end <= other_start - buffer:
            continue
        return True
    return False


def aircraft_slot_conflict(listing_id, start, end):
    listing_tx_ids = {
        t["id"]
        for t in dbmod.db["transactions"].values()
        if t["listing_id"] == listing_id
    }
    for other in dbmod.db["bookings"].values():
        if other["status"] not in ACTIVE_BOOKING_STATES:
            continue
        if other["transaction_id"] not in listing_tx_ids:
            continue
        # Strict half-open overlap; adjacency is allowed.
        if other["_start_dt"] < end and start < other["_end_dt"]:
            return True
    return False


def has_other_active_booking(transaction_id, exclude_booking_id):
    return any(
        b["transaction_id"] == transaction_id
        and b["id"] != exclude_booking_id
        and b["status"] in ACTIVE_BOOKING_STATES
        for b in dbmod.db["bookings"].values()
    )
