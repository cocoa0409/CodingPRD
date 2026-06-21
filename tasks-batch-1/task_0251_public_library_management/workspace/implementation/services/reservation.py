"""Reservation interval-overlap rules (SCAFFOLD §1.3, PRD §3.7).

ROOM  : exclusive interval with a mandatory end-side buffer (cleanup gap).
COMPUTER: aggregate capacity, no buffer; reject only when peak concurrency
          (including the new booking) would exceed resource.capacity.

"Active" reservations are those in REQUESTED, CONFIRMED, or CHECKED_IN status.
COMPLETED / NO_SHOW / CANCELLED free the window.
"""

from datetime import timedelta

import db

ACTIVE_RES_STATUSES = ("REQUESTED", "CONFIRMED", "CHECKED_IN")


def _active_reservations_for_resource(resource_id, exclude_id=None):
    return [
        r for r in db.reservations.values()
        if r["resource_id"] == resource_id
        and r["status"] in ACTIVE_RES_STATUSES
        and (exclude_id is None or r["id"] != exclude_id)
    ]


def room_conflict(resource_id, new_start, new_end, buffer_minutes, exclude_id=None):
    """ROOM conflict: windows expanded by buffer on the end side intersect.

    new conflicts with existing R when:
        new.start < R.end + buffer  AND  R.start < new.end + buffer
    Adjacency within the buffer is a conflict.
    """
    buf = timedelta(minutes=buffer_minutes)
    for r in _active_reservations_for_resource(resource_id, exclude_id):
        if new_start < (r["end_at"] + buf) and r["start_at"] < (new_end + buf):
            return True
    return False


def computer_conflict(resource_id, new_start, new_end, capacity, exclude_id=None):
    """COMPUTER conflict: peak concurrency (incl. new) would exceed capacity.

    Gather active reservations whose half-open windows strictly overlap the new
    window, add the new booking, then sweep all interval endpoints to find the
    maximum number of simultaneously overlapping reservations. Reject when that
    peak exceeds capacity.
    """
    overlapping = [
        r for r in _active_reservations_for_resource(resource_id, exclude_id)
        if r["start_at"] < new_end and new_start < r["end_at"]
    ]

    intervals = [(r["start_at"], r["end_at"]) for r in overlapping]
    intervals.append((new_start, new_end))

    # Sweep: at each start (+1) and end (-1). Process ends before starts at the
    # same instant so that touching half-open intervals don't count as concurrent.
    events = []
    for s, e in intervals:
        events.append((s, 1))
        events.append((e, -1))
    # sort by time, ends (-1) before starts (+1) at equal timestamps
    events.sort(key=lambda ev: (ev[0], ev[1]))

    peak = 0
    current = 0
    for _, delta in events:
        current += delta
        if current > peak:
            peak = current

    return peak > capacity


def has_conflict(resource, new_start, new_end, buffer_minutes, exclude_id=None):
    if resource["resource_kind"] == "ROOM":
        return room_conflict(
            resource["id"], new_start, new_end, buffer_minutes, exclude_id
        )
    return computer_conflict(
        resource["id"], new_start, new_end, resource["capacity"], exclude_id
    )
