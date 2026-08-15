"""Appointment window and conflict geometry (SCAFFOLD §1.3 window_check /
appointment_conflict_check; PRD §3.3).

Intervals are half-open [start_at, end_at): adjacent intervals do not overlap.
"""
import db
from db import store

MIN_DURATION_MINUTES = 15
MAX_DURATION_MINUTES = 120
LIVE_STATUSES = ("SCHEDULED", "CHECKED_IN")


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def violates_window(site, start_at, end_at):
    """True when any window rule is violated (all map to ERR_OUTSIDE_SITE_WINDOW)."""
    now = db.LOGICAL_CLOCK
    if start_at < now:
        return True  # start must not lie in the past
    if start_at < site["season_start"] or end_at > site["season_end"]:
        return True  # outside the inclusive season bounds
    open_mark = (site["daily_open_hour"], 0, 0, 0)
    if (start_at.hour, start_at.minute, start_at.second, start_at.microsecond) < open_mark:
        return True  # starts before the daily open hour
    close_hour = site["daily_close_hour"]
    if close_hour < 24:
        close_mark = (close_hour, 0, 0, 0)
        if (end_at.hour, end_at.minute, end_at.second, end_at.microsecond) > close_mark:
            return True  # ends after the daily close hour
    minutes = (end_at - start_at).total_seconds() / 60
    if minutes < MIN_DURATION_MINUTES or minutes > MAX_DURATION_MINUTES:
        return True
    return False


def volunteer_conflict(volunteer_id, start_at, end_at, exclude_id=None):
    """Any live appointment of the same volunteer overlapping the interval."""
    for a in store.appointments.values():
        if a["id"] == exclude_id:
            continue
        if a["volunteer_id"] != volunteer_id:
            continue
        if a["status"] not in LIVE_STATUSES:
            continue
        if overlaps(a["start_at"], a["end_at"], start_at, end_at):
            return True
    return False


def overlapping_site_count(site_id, start_at, end_at, exclude_id=None):
    """Count of the site's live appointments overlapping the interval (capacity)."""
    count = 0
    for a in store.appointments.values():
        if a["id"] == exclude_id:
            continue
        if a["site_id"] != site_id:
            continue
        if a["status"] not in LIVE_STATUSES:
            continue
        if overlaps(a["start_at"], a["end_at"], start_at, end_at):
            count += 1
    return count
