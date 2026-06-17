"""Computed-aggregate recomputation: seats_booked, catch_total, open_slot_count."""
from db import db


def recompute_seats_booked(charter):
    """Sum of party_size over Bookings in {RESERVED, CONFIRMED} for this charter."""
    total = 0
    for b in db.bookings.values():
        if b["charter_id"] == charter["id"] and b["status"] in ("RESERVED", "CONFIRMED"):
            total += b["party_size"]
    return total


def recompute_catch_total(charter):
    """Sum of kept fish (fish_count - released_count) over the charter's reports."""
    total = 0
    for r in db.catch_reports.values():
        if r["charter_id"] == charter["id"]:
            total += (r["fish_count"] - r["released_count"])
    return total


def recompute_open_slot_count(marina):
    """slot_count minus distinct busy slots (HELD/OCCUPIED reservation whose
    half-open [window_start, window_end) brackets the current clock)."""
    now = db.now()
    # Slots belonging to this marina.
    marina_slot_ids = {s["id"] for s in db.dock_slots.values()
                       if s["marina_id"] == marina["id"]}
    busy = set()
    for r in db.slot_reservations.values():
        if r["status"] not in ("HELD", "OCCUPIED"):
            continue
        if r["dock_slot_id"] not in marina_slot_ids:
            continue
        ws = r["_window_start_dt"]
        we = r["_window_end_dt"]
        if ws <= now < we:
            busy.add(r["dock_slot_id"])
    return max(0, marina["slot_count"] - len(busy))
