"""Occupancy intervals, recurrence expansion and conflict semantics (PRD 2.6,
SCAFFOLD occupied_interval / scheduling_placement bumpability rules).

Intervals are half-open: [start, end).  Two intervals conflict iff each begins
strictly before the other ends; an interval ending exactly when another begins
does NOT conflict.
"""

from datetime import timedelta

import db
from constants import (
    BUMP_SHIELD_HOURS,
    DAY_TO_WEEKDAY,
    GRANT_OUTSTANDING_STATUSES,
    OCCUPYING_EVENT_STATUSES,
    PLACEMENT_EVENT_STATUSES,
)


def overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


def occupancy_interval(event, room):
    """[start_at - setup, end_at + teardown + room.turnaround_buffer_minutes).

    The turnaround buffer is asymmetric: appended after teardown only, never
    before setup."""
    start = event["_start"] - timedelta(minutes=event.get("setup_minutes", 0))
    end = event["_end"] + timedelta(
        minutes=event.get("teardown_minutes", 0) + room.get("turnaround_buffer_minutes", 0)
    )
    return start, end


def billable_interval(event):
    """[start_at - setup, end_at + teardown) - the buffer is never billed."""
    start = event["_start"] - timedelta(minutes=event.get("setup_minutes", 0))
    end = event["_end"] + timedelta(minutes=event.get("teardown_minutes", 0))
    return start, end


def block_instances(block):
    """One instance per date in [term_start_date .. term_end_date] inclusive
    whose UTC weekday is in days_of_week: [date + start_time, date + end_time).
    Block instances carry no buffer of any kind."""
    term = db.terms.get(block.get("term_id"))
    if term is None:
        return []
    wanted = {DAY_TO_WEEKDAY[d] for d in block.get("days_of_week", [])}
    start_minutes = block["_start_time_minutes"]
    end_minutes = block["_end_time_minutes"]
    out = []
    day = term["_term_start"]
    last = term["_term_end"]
    while day <= last:
        if day.weekday() in wanted:
            out.append(
                (
                    day + timedelta(minutes=start_minutes),
                    day + timedelta(minutes=end_minutes),
                )
            )
        day += timedelta(days=1)
    return out


def term_span(term):
    """Instructional dates are inclusive: [term_start_date, term_end_date + 1d)."""
    return term["_term_start"], term["_term_end"] + timedelta(days=1)


def event_intersects_term(event, term):
    """The event's span [start_at, end_at) against the term's inclusive
    instructional dates."""
    ts, te = term_span(term)
    return overlap(event["_start"], event["_end"], ts, te)


def has_outstanding_grants(event):
    for grant in db.access_grants.values():
        if grant.get("event_id") == event["id"] and grant.get("status") in GRANT_OUTSTANDING_STATUSES:
            return True
    return False


def is_bumpable(event, now):
    """REQUESTED and APPROVED events are always bumpable; CONFIRMED only when at
    least 72 hours remain before its start and it holds no ISSUED/OVERDUE
    grants; IN_PROGRESS is never bumpable."""
    status = event.get("status")
    if status in ("REQUESTED", "APPROVED"):
        return True
    if status == "CONFIRMED":
        if has_outstanding_grants(event):
            return False
        return (event["_start"] - now) >= timedelta(hours=BUMP_SHIELD_HOURS)
    return False


def event_occupancy_conflicts(room, occ_start, occ_end, exclude_event_id=None,
                              include_blocks=False, event_statuses=OCCUPYING_EVENT_STATUSES):
    """Buffered half-open conflict check against committed events on the room,
    the room's recorded outage windows, and (optionally) PLACED block
    instances."""
    for other in db.event_reservations.values():
        if other["id"] == exclude_event_id or other.get("room_id") != room["id"]:
            continue
        if other.get("status") not in event_statuses:
            continue
        os_, oe = occupancy_interval(other, room)
        if overlap(occ_start, occ_end, os_, oe):
            return True
    for os_, oe in room.get("_outages", []):
        if overlap(occ_start, occ_end, os_, oe):
            return True
    if include_blocks:
        for block in db.academic_blocks.values():
            if block.get("status") != "PLACED" or block.get("assigned_room_id") != room["id"]:
                continue
            for bs, be in block_instances(block):
                if overlap(occ_start, occ_end, bs, be):
                    return True
    return False


def placement_conflicting_events(room, instances):
    """Events on the room whose buffered occupancy overlaps any block instance;
    placement considers REQUESTED demand in addition to committed occupancy."""
    out = []
    for other in db.event_reservations.values():
        if other.get("room_id") != room["id"]:
            continue
        if other.get("status") not in PLACEMENT_EVENT_STATUSES:
            continue
        os_, oe = occupancy_interval(other, room)
        for bs, be in instances:
            if overlap(bs, be, os_, oe):
                out.append(other)
                break
    return out


def placed_block_overlap(room, instances):
    """Any PLACED block instance on the room overlapping the given instances."""
    for block in db.academic_blocks.values():
        if block.get("status") != "PLACED" or block.get("assigned_room_id") != room["id"]:
            continue
        for bs, be in block_instances(block):
            for is_, ie in instances:
                if overlap(bs, be, is_, ie):
                    return True
    return False
