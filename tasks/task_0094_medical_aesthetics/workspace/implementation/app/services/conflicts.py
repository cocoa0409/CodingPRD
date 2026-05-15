"""Appointment conflict-check service."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..errors import ApiError
from ..store import get_store


STERILIZATION_GAP_MINUTES = 15
ACTIVE_STATUSES = ("SCHEDULED", "CHECKED_IN", "IN_PROGRESS")


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def check_appointment_conflicts(
    candidate: dict[str, Any],
    prep_window_start: datetime,
    scheduled_start: datetime,
    scheduled_end: datetime,
    exclude_id: str | None = None,
) -> None:
    """Raise the appropriate conflict error if any resource overlaps."""
    doctor_id = candidate["doctor_id"]
    nurse_id = candidate["nurse_id"]
    room_id = candidate["room_id"]
    equipment_ids = candidate["equipment_ids"]
    anesthesia_id = candidate.get("anesthesia_resource_id")

    room_end_extended = scheduled_end + timedelta(minutes=STERILIZATION_GAP_MINUTES)

    for ap in get_store().appointments.values():
        if exclude_id and ap["id"] == exclude_id:
            continue
        if ap["status"] not in ACTIVE_STATUSES:
            continue
        other_prep = _parse_iso(ap["prep_window_start"])
        other_start = _parse_iso(ap["scheduled_start"])
        other_end = _parse_iso(ap["scheduled_end"])
        other_room_end_ext = other_end + timedelta(minutes=STERILIZATION_GAP_MINUTES)

        # Doctor
        if ap["doctor_id"] == doctor_id:
            if _overlaps(prep_window_start, scheduled_end, other_prep, other_end):
                raise ApiError("ERR_DOCTOR_CONFLICT", "doctor double-booked")
        # Nurse
        if ap["nurse_id"] == nurse_id:
            if _overlaps(prep_window_start, scheduled_end, other_prep, other_end):
                raise ApiError("ERR_NURSE_CONFLICT", "nurse double-booked")
        # Room (extended interval on both sides)
        if ap["room_id"] == room_id:
            if _overlaps(prep_window_start, room_end_extended, other_prep, other_room_end_ext):
                raise ApiError("ERR_ROOM_CONFLICT", "room double-booked")
        # Equipment
        other_eq = set(ap.get("equipment_ids") or [])
        if any(eq in other_eq for eq in equipment_ids):
            if _overlaps(prep_window_start, scheduled_end, other_prep, other_end):
                raise ApiError("ERR_EQUIPMENT_CONFLICT", "equipment double-booked")
        # Anesthesia (interval is [scheduled_start, scheduled_end), no prep/gap)
        if anesthesia_id and ap.get("anesthesia_resource_id") == anesthesia_id:
            if _overlaps(scheduled_start, scheduled_end, other_start, other_end):
                raise ApiError("ERR_ANESTHESIA_CONFLICT", "anesthesia double-booked")


def _parse_iso(value: str) -> datetime:
    from ..clock import parse_iso
    return parse_iso(value)
