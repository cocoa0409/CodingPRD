"""Appointment slot-overlap (buffer-aware) helper (PRD §3.12)."""
from db import db
from services.timeutil import to_epoch

# Appointment statuses that occupy the slot for overlap purposes ("non-cancelled").
NON_CANCELLED = {"REQUESTED", "CONFIRMED", "RESCHEDULE_REQUESTED", "COMPLETED", "NO_SHOW"}
# booked_count includes these statuses (PRD §3.12).
BOOKED_STATUSES = {"REQUESTED", "CONFIRMED", "RESCHEDULE_REQUESTED", "COMPLETED"}


def overlaps_with_buffer(start_a, end_a, start_b, end_b, buffer_seconds):
    """Half-open intervals [start_a, end_a) and [start_b, end_b), each expanded
    by buffer_seconds of mandatory clear gap, overlap?

    Two intervals honor the buffer when one ends at least buffer_seconds before
    the other begins. They conflict otherwise.
    """
    return start_a < end_b + buffer_seconds and start_b < end_a + buffer_seconds


def has_conflict(slot, start_at, end_at, exclude_appointment_id=None):
    """True if [start_at, end_at) conflicts with any other non-cancelled
    appointment in the slot, honoring buffer_minutes (PRD §3.12)."""
    buffer_seconds = slot["buffer_minutes"] * 60
    s_new = to_epoch(start_at, "start_at")
    e_new = to_epoch(end_at, "end_at")
    for appt in db.appointments.values():
        if appt["slot_id"] != slot["id"]:
            continue
        if exclude_appointment_id is not None and appt["id"] == exclude_appointment_id:
            continue
        if appt["status"] not in NON_CANCELLED:
            continue
        s_other = to_epoch(appt["start_at"], "start_at")
        e_other = to_epoch(appt["end_at"], "end_at")
        if overlaps_with_buffer(s_new, e_new, s_other, e_other, buffer_seconds):
            return True
    return False
