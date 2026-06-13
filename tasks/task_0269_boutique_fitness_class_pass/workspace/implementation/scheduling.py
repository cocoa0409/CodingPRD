"""Session scheduling conflict checks (§1.3 instructor/room windows, §3.5)."""

from datetime import timedelta

import db
from errors import err
from services import INSTRUCTOR_TRAVEL_BUFFER_MIN, ROOM_CLEANING_BUFFER_MIN


def _ends_at(starts_at, template):
    return starts_at + timedelta(minutes=template["duration_min"])


def check_instructor_conflict(instructor_id, starts_at, ends_at, studio_id, exclude_session_id=None):
    """ERR_INSTRUCTOR_CONFLICT (§3.5).

    Same studio: half-open intervals strictly overlap (touching is OK).
    Different studio: gap (later.start - earlier.end, floored at 0) < 30 min.
    """
    for s in db.class_sessions.values():
        if s["id"] == exclude_session_id:
            continue
        if s["instructor_id"] != instructor_id:
            continue
        if s["status"] == "CANCELLED":
            continue
        o_start = s["starts_at"]
        o_end = s["ends_at"]
        if s["studio_id"] == studio_id:
            # Strict overlap on half-open [start, end).
            if starts_at < o_end and o_start < ends_at:
                raise err("ERR_INSTRUCTOR_CONFLICT", "Instructor double-booked")
        else:
            # Cross-studio travel buffer.
            if starts_at <= o_start:
                earlier_end, later_start = ends_at, o_start
            else:
                earlier_end, later_start = o_end, starts_at
            gap_min = max(0.0, (later_start - earlier_end).total_seconds() / 60.0)
            if gap_min < INSTRUCTOR_TRAVEL_BUFFER_MIN:
                raise err("ERR_INSTRUCTOR_CONFLICT", "Instructor needs travel buffer between studios")


def check_room_conflict(room_id, starts_at, ends_at, exclude_session_id=None):
    """ERR_ROOM_CONFLICT (§3.5).

    Each session's effective interval is [starts_at, ends_at + 15min). Two
    sessions conflict when each one's start falls before the other's padded end
    (half-open: starting exactly at the padded edge is fine).
    """
    pad = timedelta(minutes=ROOM_CLEANING_BUFFER_MIN)
    a_end_padded = ends_at + pad
    for s in db.class_sessions.values():
        if s["id"] == exclude_session_id:
            continue
        if s["room_id"] != room_id:
            continue
        if s["status"] == "CANCELLED":
            continue
        b_end_padded = s["ends_at"] + pad
        if starts_at < b_end_padded and s["starts_at"] < a_end_padded:
            raise err("ERR_ROOM_CONFLICT", "Room double-booked")


def validate_session_dependencies(studio, room, instructor):
    """ERR_STUDIO_CLOSED if studio not OPEN, room not ACTIVE, instructor not ACTIVE."""
    if studio["status"] != "OPEN":
        raise err("ERR_STUDIO_CLOSED", "Studio is closed")
    if room["status"] != "ACTIVE":
        raise err("ERR_STUDIO_CLOSED", "Room is retired")
    if instructor["status"] != "ACTIVE":
        raise err("ERR_STUDIO_CLOSED", "Instructor is inactive")
