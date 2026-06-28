"""Calendar-conflict checks for consult booking / rebooking (PRD §3.4).

Both checks consider only non-terminal consults — SCHEDULED or IN_PROGRESS — as
occupying the calendar. The consultant check runs first, the client check
second.
"""
from datetime import timedelta

import db
from errors import err, ERR_CONSULTANT_DOUBLE_BOOKED, ERR_CLIENT_DOUBLE_BOOKED
from .common import parse_iso

NON_TERMINAL = {"SCHEDULED", "IN_PROGRESS"}


def _overlaps(a_start, a_end, b_start, b_end):
    """Two half-open intervals overlap iff a.start < b.end AND b.start < a.end
    (strict). Adjacency (touching at one instant) does NOT conflict (PRD §3.4)."""
    return a_start < b_end and b_start < a_end


def _padded_interval(start, end, consult_type, buffer_minutes):
    """Consultant-axis interval. IN_HOME reserves travel_buffer_minutes on both
    sides; PRENATAL/TELEHEALTH occupy only the bare interval (PRD §3.4)."""
    if consult_type == "IN_HOME":
        pad = timedelta(minutes=buffer_minutes)
        return start - pad, end + pad
    return start, end


def check_calendar_conflicts(practice_id, client_id, consultant_id,
                             consult_type, start_iso, end_iso, exclude_id=None):
    """Run the consultant check then the client check. Raises the relevant
    double-booked error on conflict. `exclude_id` lets a reschedule ignore the
    consult being moved."""
    new_start = parse_iso(start_iso)
    new_end = parse_iso(end_iso)

    consultant = db.consultants.get(consultant_id)
    buffer_minutes = consultant["travel_buffer_minutes"] if consultant else 60

    # --- Consultant calendar (buffer-padded), checked first (PRD §3.4) ---
    new_pad_start, new_pad_end = _padded_interval(
        new_start, new_end, consult_type, buffer_minutes
    )
    for other in db.consults.values():
        if other["id"] == exclude_id:
            continue
        if other["consultant_id"] != consultant_id:
            continue
        if other["status"] not in NON_TERMINAL:
            continue
        o_start = parse_iso(other["scheduled_start_utc"])
        o_end = parse_iso(other["scheduled_end_utc"])
        o_pad_start, o_pad_end = _padded_interval(
            o_start, o_end, other["consult_type"], buffer_minutes
        )
        if _overlaps(new_pad_start, new_pad_end, o_pad_start, o_pad_end):
            raise err(ERR_CONSULTANT_DOUBLE_BOOKED,
                      "Consultant calendar conflict")

    # --- Client calendar (bare interval, no buffer), checked second (PRD §3.4) ---
    for other in db.consults.values():
        if other["id"] == exclude_id:
            continue
        if other["client_id"] != client_id:
            continue
        if other["status"] not in NON_TERMINAL:
            continue
        o_start = parse_iso(other["scheduled_start_utc"])
        o_end = parse_iso(other["scheduled_end_utc"])
        if _overlaps(new_start, new_end, o_start, o_end):
            raise err(ERR_CLIENT_DOUBLE_BOOKED, "Client calendar conflict")
