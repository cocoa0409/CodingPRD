"""Travel-lift temporal conflict and stand-row capacity (scaffold 1.3)."""

from datetime import timedelta

import db
from money import LIFT_BUFFER_MINUTES


def lift_slot_conflict(new_start, new_end, exclude_slot_id=None):
    """Every BOOKED or COMPLETED slot (any job) competes for the single lift
    with a 30-minute turnaround buffer. Conflict iff:
        new_start < existing_end + 30min AND existing_start < new_end + 30min
    Strict inequalities: exact buffer adjacency does NOT conflict."""
    buffer = timedelta(minutes=LIFT_BUFFER_MINUTES)
    for s in db.slots.values():
        if s["status"] not in ("BOOKED", "COMPLETED"):
            continue
        if exclude_slot_id is not None and s["id"] == exclude_slot_id:
            continue
        if new_start < s["_end"] + buffer and s["_start"] < new_end + buffer:
            return True
    return False


def stands_projected(row_id, new_start_date, new_end_date):
    """Closed-interval occupancy: two windows intersect iff
    a.start <= b.end AND b.start <= a.end (touching dates intersect)."""
    projected = 0
    for a in db.assignments.values():
        if a["row_id"] != row_id or a["status"] != "ACTIVE":
            continue
        if a["_start_date"] <= new_end_date and new_start_date <= a["_end_date"]:
            projected += a["stands_used"]
    return projected


def stands_capacity_exceeded(row, new_start_date, new_end_date, stands_used):
    """Reject iff projected + requested > total_stands; exactly full passes."""
    projected = stands_projected(row["id"], new_start_date, new_end_date)
    return (projected + stands_used) > row["total_stands"]
