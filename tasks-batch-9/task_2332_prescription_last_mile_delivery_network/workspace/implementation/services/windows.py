"""Capacity-window occupancy and interval rules."""

from constants import AFTER_HOURS_END_UTC_HOUR, AFTER_HOURS_START_UTC_HOUR
from db import db, touch
from errors import api_error
from services import derive


def is_after_hours(window_start):
    hour = window_start.hour
    return hour >= AFTER_HOURS_START_UTC_HOUR or hour < AFTER_HOURS_END_UTC_HOUR


def refresh_status(window):
    """OPEN <-> FULL from occupancy. CLOSED is sticky: only the sweep sets it."""
    if window["status"] == "CLOSED":
        return
    reserved = derive.reserved_slots(window)
    if reserved >= window["capacity_slots"]:
        window["status"] = "FULL"
    elif window["status"] == "FULL" and db.clock < window["window_end"]:
        window["status"] = "OPEN"


def occupancy_changed(window):
    """Called after any reservation or release; the version always bumps."""
    if window is None:
        return
    refresh_status(window)
    touch(window)


def assert_no_overlap(zone_id, courier_mode, start, end):
    """Half-open comparison: adjacency is not a conflict."""
    for existing in db.delivery_windows.values():
        if existing["zone_id"] != zone_id:
            continue
        if existing["courier_mode"] != courier_mode:
            continue
        if existing["status"] == "CLOSED":
            continue
        if start < existing["window_end"] and existing["window_start"] < end:
            raise api_error("ERR_WINDOW_OVERLAP",
                            "The candidate interval overlaps an existing window of the "
                            "same zone and courier mode.")
