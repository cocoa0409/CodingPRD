"""Existence lookups and shared temporal/window helpers (PRD §2.6, §2.7, §3.3)."""

from datetime import timedelta

from db import db
from clock import parse_iso
from errors import raise_err, ERR_NOT_FOUND


def get_or_404(collection, key, label="resource"):
    rec = collection.get(key)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "%s not found" % label)
    return rec


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test (PRD §3.3): back-to-back is allowed."""
    return a_start < b_end and b_start < a_end


def bay_window_conflict(bay_id, start_dt, end_dt, exclude_reservation_id=None):
    """True if [start,end) overlaps a CONFIRMED reservation or SCHEDULED lesson
    on the same bay (PRD §3.3 / §3.11)."""
    for r in db.reservations.values():
        if r["id"] == exclude_reservation_id:
            continue
        if r["bay_id"] == bay_id and r["status"] == "CONFIRMED":
            if overlaps(start_dt, end_dt, parse_iso(r["start_utc"]), parse_iso(r["end_utc"])):
                return True
    for le in db.lessons.values():
        if le["bay_id"] == bay_id and le["status"] == "SCHEDULED":
            if overlaps(start_dt, end_dt, parse_iso(le["start_utc"]), parse_iso(le["end_utc"])):
                return True
    return False


def minutes_between(earlier_dt, later_dt):
    return (later_dt - earlier_dt).total_seconds() / 60.0


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
