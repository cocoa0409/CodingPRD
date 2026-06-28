"""Time-interval overlap helpers for room/teacher double-booking checks (PRD §3.2, §3.9)."""
from datetime import timedelta

import constants as C
from db import store
from clock import parse_iso

NON_CANCELLED_SESSION = {"SCHEDULED", "OPEN", "FULL", "IN_PROGRESS", "COMPLETED"}
NON_CANCELLED_WORKSHOP = {"DRAFT", "OPEN", "FULL", "CLOSED"}


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open overlap: [a_start, a_end) intersects [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


def session_room_conflict(new_session):
    """A non-CANCELLED ClassSession on the same room overlapping [start, end) (half-open)."""
    ns = parse_iso(new_session["start_utc"])
    ne = parse_iso(new_session["end_utc"])
    for s in store.class_sessions.values():
        if s["id"] == new_session["id"]:
            continue
        if s["room_id"] != new_session["room_id"]:
            continue
        if s["status"] not in NON_CANCELLED_SESSION:
            continue
        if _intervals_overlap(ns, ne, parse_iso(s["start_utc"]), parse_iso(s["end_utc"])):
            return True
    return False


def session_teacher_conflict(new_session):
    """Teacher committed to another non-CANCELLED session OR workshop overlapping."""
    ns = parse_iso(new_session["start_utc"])
    ne = parse_iso(new_session["end_utc"])
    tid = new_session["teacher_id"]
    for s in store.class_sessions.values():
        if s["id"] == new_session["id"]:
            continue
        if s["teacher_id"] != tid:
            continue
        if s["status"] not in NON_CANCELLED_SESSION:
            continue
        if _intervals_overlap(ns, ne, parse_iso(s["start_utc"]), parse_iso(s["end_utc"])):
            return True
    for w in store.workshops.values():
        if w["lead_teacher_id"] != tid:
            continue
        if w["status"] not in NON_CANCELLED_WORKSHOP:
            continue
        if _intervals_overlap(ns, ne, parse_iso(w["start_utc"]), parse_iso(w["end_utc"])):
            return True
    return False


def workshop_room_conflict(new_workshop):
    """Buffer-inclusive: workshop must clear every other non-CANCELLED workshop AND
    every non-CANCELLED class session in the same room by WORKSHOP_BUFFER_MINUTES
    on each side.
    """
    buf = timedelta(minutes=C.WORKSHOP_BUFFER_MINUTES)
    ws = parse_iso(new_workshop["start_utc"]) - buf
    we = parse_iso(new_workshop["end_utc"]) + buf
    rid = new_workshop["room_id"]
    for w in store.workshops.values():
        if w["id"] == new_workshop["id"]:
            continue
        if w["room_id"] != rid:
            continue
        if w["status"] not in NON_CANCELLED_WORKSHOP:
            continue
        if _intervals_overlap(ws, we, parse_iso(w["start_utc"]), parse_iso(w["end_utc"])):
            return True
    for s in store.class_sessions.values():
        if s["room_id"] != rid:
            continue
        if s["status"] not in NON_CANCELLED_SESSION:
            continue
        if _intervals_overlap(ws, we, parse_iso(s["start_utc"]), parse_iso(s["end_utc"])):
            return True
    return False


def workshop_teacher_conflict(new_workshop):
    """Lead teacher committed to another non-CANCELLED session or workshop overlapping."""
    ws = parse_iso(new_workshop["start_utc"])
    we = parse_iso(new_workshop["end_utc"])
    tid = new_workshop["lead_teacher_id"]
    for s in store.class_sessions.values():
        if s["teacher_id"] != tid:
            continue
        if s["status"] not in NON_CANCELLED_SESSION:
            continue
        if _intervals_overlap(ws, we, parse_iso(s["start_utc"]), parse_iso(s["end_utc"])):
            return True
    for w in store.workshops.values():
        if w["id"] == new_workshop["id"]:
            continue
        if w["lead_teacher_id"] != tid:
            continue
        if w["status"] not in NON_CANCELLED_WORKSHOP:
            continue
        if _intervals_overlap(ws, we, parse_iso(w["start_utc"]), parse_iso(w["end_utc"])):
            return True
    return False
