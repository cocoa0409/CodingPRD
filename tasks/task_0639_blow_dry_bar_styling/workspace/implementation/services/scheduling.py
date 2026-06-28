"""Scheduling validations (PRD §3.4): operating windows, chair/stylist overlap,
event-block membership, reserved-chair exclusion.

Non-terminal appointment = lifecycle_status not in {COMPLETED, NO_SHOW, CANCELLED}.
"""

from db import db

TERMINAL_LIFECYCLE = {"COMPLETED", "NO_SHOW", "CANCELLED"}


def non_terminal_appointments():
    return [a for a in db.appointments.values()
            if a["lifecycle_status"] not in TERMINAL_LIFECYCLE]


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap test: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


def chair_conflict(chair, start_minute, end_minute, exclude_appt_id=None):
    """A new/updated appointment occupies [start, end + buffer) on the chair.
    Returns True if it overlaps any non-terminal appointment on that chair.
    The buffer trails each appointment (applied after the existing one too)."""
    buffer = chair["turnover_buffer_minutes"]
    new_start = start_minute
    new_end = end_minute + buffer
    for a in db.appointments.values():
        if a["id"] == exclude_appt_id:
            continue
        if a["chair_id"] != chair["id"]:
            continue
        if a["lifecycle_status"] in TERMINAL_LIFECYCLE:
            continue
        existing_start = a["start_minute"]
        existing_end = a["end_minute"] + buffer
        if overlaps(new_start, new_end, existing_start, existing_end):
            return True
    return False


def stylist_conflict(stylist_id, start_minute, end_minute, exclude_appt_id=None):
    """[start, end) overlap with any non-terminal appointment for the stylist, no buffer."""
    for a in db.appointments.values():
        if a["id"] == exclude_appt_id:
            continue
        if a["stylist_id"] != stylist_id:
            continue
        if a["lifecycle_status"] in TERMINAL_LIFECYCLE:
            continue
        if overlaps(start_minute, end_minute, a["start_minute"], a["end_minute"]):
            return True
    return False


def chair_reserved_by_confirmed_block(chair_id, start_minute, end_minute, own_block_id=None):
    """Standalone booking exclusion: a chair reserved by a CONFIRMED block during
    its window holds the chair exclusively. Returns True if [start,end) falls in
    such a window on a reserved chair (ignoring the booking's own block)."""
    for b in db.event_blocks.values():
        if own_block_id is not None and b["id"] == own_block_id:
            continue
        if b["status"] != "CONFIRMED":
            continue
        if chair_id not in b["reserved_chair_ids"]:
            continue
        if overlaps(start_minute, end_minute, b["window_start_minute"], b["window_end_minute"]):
            return True
    return False
