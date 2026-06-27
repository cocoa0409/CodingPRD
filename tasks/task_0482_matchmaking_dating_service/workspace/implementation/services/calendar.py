"""Calendar overlap and buffer checks (PRD §3.6, §3.7)."""
from datetime import timedelta

from db import db
from services.common import parse_iso

COACHING_BUFFER_MIN = 30


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test. Touching endpoints do NOT collide."""
    return a_start < b_end and b_start < a_end


def member_scheduled_dates(member_id, exclude_id=None):
    out = []
    for de in db.date_events.values():
        if de["status"] != "SCHEDULED":
            continue
        if de["scheduled_by_member_id"] != member_id:
            continue
        if exclude_id and de["id"] == exclude_id:
            continue
        out.append(de)
    return out


def member_booked_sessions(member_id, exclude_id=None):
    out = []
    for cs in db.coaching_sessions.values():
        if cs["status"] != "BOOKED":
            continue
        if cs["member_id"] != member_id:
            continue
        if exclude_id and cs["id"] == exclude_id:
            continue
        out.append(cs)
    return out


def date_overlaps_existing(member_id, start_dt, end_dt):
    """A new date must not overlap any SCHEDULED date OR BOOKED coaching session
    of the scheduling member."""
    for de in member_scheduled_dates(member_id):
        if _overlaps(start_dt, end_dt, parse_iso(de["start_at"]), parse_iso(de["end_at"])):
            return True
    for cs in member_booked_sessions(member_id):
        if _overlaps(start_dt, end_dt, parse_iso(cs["start_at"]), parse_iso(cs["end_at"])):
            return True
    return False


def session_overlaps_existing(member_id, start_dt, end_dt):
    """A new coaching session must not overlap the member's other SCHEDULED dates
    or BOOKED sessions."""
    for de in member_scheduled_dates(member_id):
        if _overlaps(start_dt, end_dt, parse_iso(de["start_at"]), parse_iso(de["end_at"])):
            return True
    for cs in member_booked_sessions(member_id):
        if _overlaps(start_dt, end_dt, parse_iso(cs["start_at"]), parse_iso(cs["end_at"])):
            return True
    return False


def session_violates_buffer(member_id, start_dt, end_dt):
    """A new coaching session must keep a closed 30-minute gap from the member's
    SCHEDULED dates. A gap of exactly 30 min is allowed; 29 min collides."""
    buffer = timedelta(minutes=COACHING_BUFFER_MIN)
    for de in member_scheduled_dates(member_id):
        d_start = parse_iso(de["start_at"])
        d_end = parse_iso(de["end_at"])
        if _overlaps(start_dt, end_dt, d_start, d_end):
            # genuine overlap is handled by overlap check; treat as conflict too
            return True
        # gap between the two intervals
        if end_dt <= d_start:
            gap = d_start - end_dt
        elif d_end <= start_dt:
            gap = start_dt - d_end
        else:
            gap = timedelta(0)
        if gap < buffer:
            return True
    return False
