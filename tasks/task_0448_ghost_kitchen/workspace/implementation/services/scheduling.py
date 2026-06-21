"""Equipment scheduling: overlap + turnaround-buffer compatibility (PRD §2.8).

Windows are half-open [start_minute, end_minute) in absolute minutes since the
Unix epoch. Two bookings on the same unit are compatible only if a full buffer
separates them in BOTH directions:
  - a new booking may start no earlier than existing.end_minute + buffer
    (lower bound inclusive: starting exactly there is allowed)
  - an existing booking may begin no earlier than new.end_minute + buffer
Only HELD bookings occupy the schedule.
"""
from db import store


def held_bookings_for(equipment_id):
    return [
        b for b in store.bookings.values()
        if b["equipment_id"] == equipment_id and b["status"] == "HELD"
    ]


def window_is_free(equipment, start_minute, end_minute, exclude_booking_id=None):
    """True iff [start_minute, end_minute) respects every existing HELD booking
    on this unit with the unit's turnaround_buffer_minutes on both sides."""
    buffer_min = equipment.get("turnaround_buffer_minutes", 0)
    for b in held_bookings_for(equipment["id"]):
        if exclude_booking_id is not None and b["id"] == exclude_booking_id:
            continue
        es, ee = b["start_minute"], b["end_minute"]
        # New may start at existing.end + buffer or later (after existing).
        new_after = start_minute >= ee + buffer_min
        # Existing may start at new.end + buffer or later (before existing).
        existing_after = es >= end_minute + buffer_min
        if not (new_after or existing_after):
            return False
    return True
