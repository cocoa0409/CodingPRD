"""Visit interval overlap helpers (PRD §3.4 on-site overlap, §3.8 buffered callback)."""
from datetime import timedelta

import db

# Visit states considered terminal for overlap purposes
TERMINAL_VISIT_STATES = {"FINISHED", "ABORTED"}


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test. Touching at a boundary is NOT overlap."""
    return a_start < b_end and b_start < a_end


def onsite_overlap(mechanic_id, start, end, exclude_visit_id=None):
    """True if [start,end) overlaps an existing non-terminal ON_SITE visit for the mechanic."""
    for v in db.store.job_visits.values():
        if v["mechanic_id"] != mechanic_id:
            continue
        if exclude_visit_id is not None and v["id"] == exclude_visit_id:
            continue
        if v["visit_status"] in TERMINAL_VISIT_STATES:
            continue
        if v["routing_mode"] != "ON_SITE":
            continue
        vs = db._parse_iso(v["scheduled_start_utc"])
        ve = db._parse_iso(v["scheduled_end_utc"])
        if _intervals_overlap(start, end, vs, ve):
            return True
    return False


def buffered_callback_conflict(mechanic_id, start, end):
    """True if [start,end) extended by CALLBACK_BUFFER_MINUTES on each side overlaps
    any existing non-terminal visit (any routing) for the mechanic."""
    buf = timedelta(minutes=db.CALLBACK_BUFFER_MINUTES)
    bstart = start - buf
    bend = end + buf
    for v in db.store.job_visits.values():
        if v["mechanic_id"] != mechanic_id:
            continue
        if v["visit_status"] in TERMINAL_VISIT_STATES:
            continue
        vs = db._parse_iso(v["scheduled_start_utc"])
        ve = db._parse_iso(v["scheduled_end_utc"])
        if _intervals_overlap(bstart, bend, vs, ve):
            return True
    return False
