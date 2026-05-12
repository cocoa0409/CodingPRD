"""Time-conflict checks across applications/activities."""
from __future__ import annotations

import db
from clock import parse_iso


NON_TERMINAL_FOR_CONFLICT = {"APPROVED", "CHECKED_IN", "ON_LEAVE", "COMPLETED"}


def overlaps_closed(a_start, a_end, b_start, b_end) -> bool:
    """Closed-closed overlap: touching endpoints DO count as conflict."""
    return not (a_end < b_start or b_end < a_start)


def has_time_conflict(volunteer_id: str, target_activity: dict,
                      exclude_application_id: str | None = None) -> bool:
    """True if the volunteer has another non-terminal application whose
    activity time-window overlaps target_activity's window."""
    t_start = parse_iso(target_activity["start_at"])
    t_end = parse_iso(target_activity["end_at"])
    target_id = target_activity["id"]
    for app in db.applications.values():
        if app["volunteer_id"] != volunteer_id:
            continue
        if exclude_application_id and app["id"] == exclude_application_id:
            continue
        if app["status"] not in NON_TERMINAL_FOR_CONFLICT:
            continue
        if app["activity_id"] == target_id:
            continue  # same activity is not a conflict with itself
        other = db.activities.get(app["activity_id"])
        if not other:
            continue
        o_start = parse_iso(other["start_at"])
        o_end = parse_iso(other["end_at"])
        if overlaps_closed(t_start, t_end, o_start, o_end):
            return True
    return False
