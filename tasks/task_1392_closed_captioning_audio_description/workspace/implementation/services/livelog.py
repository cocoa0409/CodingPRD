"""Live-side calculations (PRD §3.6-§3.7): booked_minutes, committed minutes,
buffered half-open occupancy overlap, and the auto_offer_selector."""
from datetime import timedelta

from db import DB
from util import ceil_div

COMMITTED_STATUSES = {"ACCEPTED", "CONFIRMED", "LIVE"}
# Exclusion memory: a stenographer with one of these assignment states for an
# event is never re-offered that event.
EXCLUSION_STATUSES = {"DECLINED", "PREEMPTED", "NO_SHOW", "OFFER_EXPIRED"}
HELD_STATUSES = {"OFFERED", "ACCEPTED", "CONFIRMED", "LIVE"}


def booked_minutes(event):
    """ceil((end_at - start_at)/60s) + prep_minutes + wrap_minutes."""
    air_seconds = int((event["end_at"] - event["start_at"]).total_seconds())
    return ceil_div(air_seconds, 60) + event["prep_minutes"] + event["wrap_minutes"]


def occupancy_window(event):
    """[start_at - prep_minutes, end_at + wrap_minutes): half-open, asymmetric
    buffers (prep on the left, wrap on the right)."""
    return (
        event["start_at"] - timedelta(minutes=event["prep_minutes"]),
        event["end_at"] + timedelta(minutes=event["wrap_minutes"]),
    )


def committed_minutes(stenographer_id, day_date):
    """Sum of booked_minutes over the stenographer's assignments in
    {ACCEPTED, CONFIRMED, LIVE} whose events start on the given UTC day."""
    total = 0
    for a in DB.assignments.values():
        if a["stenographer_id"] != stenographer_id:
            continue
        if a["assignment_status"] not in COMMITTED_STATUSES:
            continue
        ev = DB.live_events[a["live_event_id"]]
        if ev["start_at"].date() == day_date:
            total += a["booked_minutes"]
    return total


def has_overlap_conflict(stenographer_id, candidate_event):
    """Conflict iff candidate window W and any existing committed-set window X
    over the same stenographer satisfy W.start < X.end AND W.end > X.start.
    Touching edges are NOT a conflict."""
    ws, we = occupancy_window(candidate_event)
    for a in DB.assignments.values():
        if a["stenographer_id"] != stenographer_id:
            continue
        if a["assignment_status"] not in COMMITTED_STATUSES:
            continue
        ev = DB.live_events[a["live_event_id"]]
        xs, xe = occupancy_window(ev)
        if ws < xe and we > xs:
            return True
    return False


def eligible_basic(stenographer, event):
    """ACTIVE, exact certification match, cert_valid_until >= event.end_at."""
    if stenographer["steno_status"] != "ACTIVE":
        return False
    if stenographer["certification"] != event["required_certification"]:
        return False
    if stenographer["cert_valid_until"] < event["end_at"]:
        return False
    return True


def auto_offer_select(event):
    """Candidate pool + ranking per auto_offer_selector. Returns the winning
    Stenographer record or None when the pool is empty."""
    day = event["start_at"].date()
    bm = booked_minutes(event)
    pool = []
    for s in DB.stenographers.values():
        if not eligible_basic(s, event):
            continue
        skip = False
        for a in DB.assignments.values():
            if a["live_event_id"] != event["id"] or a["stenographer_id"] != s["id"]:
                continue
            if a["assignment_status"] in HELD_STATUSES or a["assignment_status"] in EXCLUSION_STATUSES:
                skip = True
                break
        if skip:
            continue
        if has_overlap_conflict(s["id"], event):
            continue
        if committed_minutes(s["id"], day) + bm > s["max_daily_live_minutes"]:
            continue
        pool.append(s)
    # Ranking: committed minutes on the event day ASC, then certified_since
    # ASC (seniority wins ties), then created_at ASC.
    pool.sort(key=lambda s: (committed_minutes(s["id"], day), s["certified_since"], s["created_at"], s["_seq"]))
    return pool[0] if pool else None
