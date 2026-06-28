"""Lounge bay-capacity / operating-window checks (PRD §3.8) and mobile route
turnaround-buffer checks (PRD §3.12).
"""
from datetime import timedelta

import db


def end_at(appt):
    return appt["start_at"] + timedelta(minutes=appt["duration_minutes"])


def _overlaps(a_start, a_end, b_start, b_end):
    # Half-open intervals overlap iff a_start < b_end AND b_start < a_end.
    # Touching at a boundary (a_end == b_start) does NOT overlap.
    return a_start < b_end and b_start < a_end


def lounge_ok(candidate, lounge):
    """True iff the candidate lounge slot fits the operating window AND does
    not exceed bay_count concurrent overlapping appointments."""
    start = candidate["start_at"]
    end = end_at(candidate)

    # Operating window: minutes after midnight UTC; must not cross midnight.
    start_minute = start.hour * 60 + start.minute
    # end minute measured from the same midnight as start.
    end_minute = start_minute + candidate["duration_minutes"]
    if start_minute < lounge["open_minute_of_day"]:
        return False
    if end_minute > lounge["close_minute_of_day"]:
        return False
    # Crossing midnight: end_minute beyond 1440 means the slot left the day.
    if end_minute > 1440:
        return False

    # Capacity: count overlapping SCHEDULED/DISPATCHED/IN_PROGRESS lounge
    # appointments at the same lounge.
    concurrent = 0
    for other in db.appointments.values():
        if other["id"] == candidate["id"]:
            continue
        if other["location_type"] != "LOUNGE":
            continue
        if other["lounge_id"] != lounge["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "DISPATCHED", "IN_PROGRESS"):
            continue
        if _overlaps(start, end, other["start_at"], end_at(other)):
            concurrent += 1
    if concurrent >= lounge["bay_count"]:
        return False
    return True


def route_buffer_ok(candidate, route):
    """True iff the candidate mobile stop respects the route turnaround buffer
    against every other non-cancelled stop already on the route.

    Acceptable iff candidate.end + B <= S.start OR S.end + B <= candidate.start
    (inclusive: gap == B allowed, gap < B rejected).
    """
    buffer = timedelta(minutes=route["turnaround_minutes"])
    c_start = candidate["start_at"]
    c_end = end_at(candidate)
    for other in db.appointments.values():
        if other["id"] == candidate["id"]:
            continue
        if other["route_id"] != route["id"]:
            continue
        if other["status"] == "CANCELLED":
            continue
        s_start = other["start_at"]
        s_end = end_at(other)
        ok = (c_end + buffer <= s_start) or (s_end + buffer <= c_start)
        if not ok:
            return False
    return True
