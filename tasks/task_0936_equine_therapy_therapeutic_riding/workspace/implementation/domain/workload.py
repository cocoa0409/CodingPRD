"""Horse workload ledgers and the three interval rules (PRD §3.3, §3.4)."""

from datetime import timedelta

from core import timeutil as T
from core.constants import (
    HORSE_MAX_MOUNTED_MINUTES_PER_DAY,
    HORSE_MAX_MOUNTED_MINUTES_PER_WEEK,
    HORSE_REST_INTERVAL_MINUTES,
)
from core.store import db

LIVE_STATUSES = ("CREW_PENDING", "CONFIRMED", "COMPLETED")
VARIANT_FILTER = {
    "committed": LIVE_STATUSES,
    "delivered": ("COMPLETED",),
}


def horse_sessions(horse_id, exclude_id=None):
    return [s for s in db["sessions"].values()
            if s["horse_id"] == horse_id and s["id"] != exclude_id]


def _minutes_of(session, variant):
    if variant == "delivered":
        return session.get("mounted_minutes") or 0
    return session["duration_minutes"]


def day_window(on_date):
    start = T.date_to_instant(on_date)
    return start, start + timedelta(days=1)


def week_window(on_date):
    start = T.date_to_instant(T.week_start(on_date))
    return start, start + timedelta(days=7)


def minutes_in_window(horse_id, window, variant):
    start, end = window
    statuses = VARIANT_FILTER[variant]
    total = 0
    for session in db["sessions"].values():
        if session["horse_id"] != horse_id:
            continue
        if session["schedule_status"] not in statuses:
            continue
        moment = session["scheduled_start"].dt
        if start <= moment < end:
            total += _minutes_of(session, variant)
    return total


def session_count_in_window(horse_id, window, variant):
    start, end = window
    statuses = VARIANT_FILTER[variant]
    total = 0
    for session in db["sessions"].values():
        if session["horse_id"] != horse_id:
            continue
        if session["schedule_status"] not in statuses:
            continue
        moment = session["scheduled_start"].dt
        if start <= moment < end:
            total += 1
    return total


def workload_view(horse_id, on_date, variant):
    day = day_window(on_date)
    week = week_window(on_date)
    day_minutes = minutes_in_window(horse_id, day, variant)
    week_minutes = minutes_in_window(horse_id, week, variant)
    return {
        "horse_id": horse_id,
        "week_start_date": T.date_str(T.week_start(on_date)),
        "variant": variant,
        "day_session_count": session_count_in_window(horse_id, day, variant),
        "day_minutes": day_minutes,
        "week_minutes": week_minutes,
        "day_remaining_minutes": HORSE_MAX_MOUNTED_MINUTES_PER_DAY - day_minutes,
        "week_remaining_minutes": HORSE_MAX_MOUNTED_MINUTES_PER_WEEK - week_minutes,
    }


# ------------------------------------------------------------- interval rules
def horse_overlap(horse_id, start, end):
    """Half-open: conflict when new.start < each.end AND each.start < new.end."""
    for session in db["sessions"].values():
        if session["horse_id"] != horse_id:
            continue
        if session["schedule_status"] not in LIVE_STATUSES:
            continue
        other_start = session["scheduled_start"].dt
        other_end = session["scheduled_end"].dt
        if start < other_end and other_start < end:
            return session
    return None


def horse_rest_violation(horse_id, start, end):
    """Evaluated only when no overlap was found: every neighbouring gap >= 15 min."""
    limit = timedelta(minutes=HORSE_REST_INTERVAL_MINUTES)
    for session in db["sessions"].values():
        if session["horse_id"] != horse_id:
            continue
        if session["schedule_status"] not in LIVE_STATUSES:
            continue
        other_start = session["scheduled_start"].dt
        other_end = session["scheduled_end"].dt
        if end <= other_start:
            gap = other_start - end
        elif other_end <= start:
            gap = start - other_end
        else:
            continue
        if gap < limit:
            return session
    return None


def instructor_overlap(instructor_ids, start, end, exclude_id=None):
    """Half-open, zero buffer, either instructor slot."""
    wanted = {i for i in instructor_ids if i}
    for session in db["sessions"].values():
        if session["id"] == exclude_id:
            continue
        if session["schedule_status"] not in LIVE_STATUSES:
            continue
        named = {session["instructor_id"], session.get("supervising_instructor_id")}
        if not (named & wanted):
            continue
        other_start = session["scheduled_start"].dt
        other_end = session["scheduled_end"].dt
        if start < other_end and other_start < end:
            return session
    return None


def volunteer_overlap(volunteer_id, session):
    """CLOSED intervals, zero buffer: touching endpoints DO conflict."""
    start = session["scheduled_start"].dt
    end = session["scheduled_end"].dt
    for assignment in db["crew_assignments"].values():
        if assignment["volunteer_id"] != volunteer_id:
            continue
        if assignment["status"] != "ASSIGNED":
            continue
        other = db["sessions"].get(assignment["session_id"])
        if other is None or other["id"] == session["id"]:
            continue
        if other["schedule_status"] not in ("CREW_PENDING", "CONFIRMED"):
            continue
        other_start = other["scheduled_start"].dt
        other_end = other["scheduled_end"].dt
        if start <= other_end and other_start <= end:
            return other
    return None
