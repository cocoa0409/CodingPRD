"""Engineer capacity / slot-overlap evaluation (PRD section 2.6).

Half-open interval semantics: [start, end). Two slots that merely touch at a
boundary do not conflict.
"""
import math

import db
from errors import ApiError, ERR_SLOT_CONFLICT, ERR_CAPACITY_EXCEEDED
from services.sweep import slot_counts_as_active


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def engineer_overlap(eng_id, win_start, win_end, now=None):
    """Return the conflicting slot for the engineer in the window, or None."""
    now = now or db.now_dt()
    for s in db.session_slots.values():
        if s['engineer_id'] != eng_id:
            continue
        if not slot_counts_as_active(s, now):
            continue
        ss = db.parse_dt(s['slot_start_at'])
        se = db.parse_dt(s['slot_end_at'])
        if overlaps(win_start, win_end, ss, se):
            return s
    return None


def booked_minutes_in_window(eng_id, win_start, win_end, now=None):
    now = now or db.now_dt()
    total = 0
    for s in db.session_slots.values():
        if s['engineer_id'] != eng_id:
            continue
        if not slot_counts_as_active(s, now):
            continue
        ss = db.parse_dt(s['slot_start_at'])
        se = db.parse_dt(s['slot_end_at'])
        lo = max(ss, win_start)
        hi = min(se, win_end)
        if lo < hi:
            total += int((hi - lo).total_seconds() // 60)
    return total


def remaining_capacity(engineer, win_start, win_end, now=None):
    booked = booked_minutes_in_window(engineer['id'], win_start, win_end, now)
    days = math.ceil((win_end - win_start).total_seconds() / 86400)
    capacity = engineer['capacity_minutes_per_day'] * days
    return capacity - booked


def select_engineer(win_start, win_end, duration_minutes):
    """Pick the first AVAILABLE engineer (creation order) with no overlap and
    enough remaining capacity in the window. Raises ERR_SLOT_CONFLICT (priority 7)
    before ERR_CAPACITY_EXCEEDED (priority 8) when no engineer qualifies."""
    now = db.now_dt()
    candidates = [e for e in sorted(db.engineers.values(), key=lambda e: e['_seq'])
                  if e['availability_status'] == 'AVAILABLE']
    saw_overlap = False
    for eng in candidates:
        if engineer_overlap(eng['id'], win_start, win_end, now) is not None:
            saw_overlap = True
            continue
        if remaining_capacity(eng, win_start, win_end, now) >= duration_minutes:
            return eng
    if saw_overlap:
        raise ApiError(ERR_SLOT_CONFLICT, 409,
                       'Requested window overlaps an existing BOOKED or HELD slot')
    raise ApiError(ERR_CAPACITY_EXCEEDED, 422,
                   "No available engineer's remaining capacity covers the requested duration")
