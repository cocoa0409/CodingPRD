"""Dock-door interval assignment and carrier day capacity (PRD 3.7)."""

from datetime import timedelta

import db
from errors import ApiError
from util import UTC


def _scheduled_at(warehouse_id):
    return [
        row for row in db.ordered(db.appointments.values())
        if row["warehouse_id"] == warehouse_id
        and row["appointment_status"] == "SCHEDULED"
    ]


def _conflicts(requested_start, requested_end, existing, buffer):
    """Buffered overlap, applied to both sides of the comparison."""
    return (
        requested_start < existing["window_end_at"] + buffer
        and existing["window_start_at"] < requested_end + buffer
    )


def assign_dock_door(warehouse, requested_start, requested_end):
    """Lowest-numbered door with no buffered conflict; else exhausted."""
    buffer = timedelta(minutes=int(warehouse.get("turnaround_buffer_minutes") or 0))
    occupied = _scheduled_at(warehouse["id"])
    for door in range(1, int(warehouse["dock_door_count"]) + 1):
        clash = False
        for existing in occupied:
            if existing.get("dock_door_number") != door:
                continue
            if _conflicts(requested_start, requested_end, existing, buffer):
                clash = True
                break
        if not clash:
            return door
    raise ApiError("ERR_DOCK_CAPACITY_EXHAUSTED")


def check_carrier_day_capacity(carrier, requested_start):
    """Same UTC calendar date, SCHEDULED appointments only."""
    day = requested_start.astimezone(UTC).date()
    booked = 0
    for row in db.appointments.values():
        if row["carrier_id"] != carrier["id"]:
            continue
        if row["appointment_status"] != "SCHEDULED":
            continue
        if row["window_start_at"].astimezone(UTC).date() == day:
            booked += 1
    if booked + 1 > int(carrier["daily_pickup_capacity"]):
        raise ApiError("ERR_CARRIER_DAY_CAPACITY_FULL")
