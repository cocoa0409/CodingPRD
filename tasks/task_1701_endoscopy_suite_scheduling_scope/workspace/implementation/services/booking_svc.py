"""Booking window math, room overlap/capacity rules, and lifecycle cascades."""
from datetime import timedelta

from db import db
from errors import (
    raise_error,
    ERR_SCHEDULED_START_IN_PAST,
    ERR_PREP_LEAD_TIME_INSUFFICIENT,
    ERR_ROOM_TIME_CONFLICT,
    ERR_ROOM_DAY_CAPACITY_EXCEEDED,
)
from services.core import touch
from util import age_at, now, parse_date

# calculations.procedure_occupancy_minutes constants
AGE_THRESHOLD_YEARS = 65
AGE_ADDON_MIN = 5
ANESTHESIA_ADDON = {"NONE": 0, "MAC": 10, "GENERAL": 15}

# calculations.room_block_window constants
TURNOVER_BY_ROOM_CLASS = {"STANDARD": 15, "ERCP_CAPABLE": 25}
ROOM_DAY_CAPACITY_MINUTES = 480

# prep lead times (PRD 3.2)
PREP_LEAD_HOURS = {"NONE": 0, "CLEAR_LIQUIDS": 8, "SPLIT_DOSE": 24}

# Booking-axis statuses that still hold their room block (released set excluded)
BLOCK_HOLDING_STATUSES = {"SCHEDULED", "CHECKED_IN", "IN_PROGRESS", "COMPLETED", "ABORTED_PREP_INADEQUATE"}


def patient_age_at_start(patient, scheduled_start) -> int:
    return age_at(parse_date(patient["date_of_birth"]), scheduled_start)


def compute_window(patient, procedure_type, room, scheduled_start, anesthesia_type):
    """procedure_occupancy_minutes (scheduled variant) + room_block_window."""
    minutes = (
        procedure_type["base_duration_minutes"]
        + ANESTHESIA_ADDON[anesthesia_type]
        + (AGE_ADDON_MIN if patient_age_at_start(patient, scheduled_start) >= AGE_THRESHOLD_YEARS else 0)
    )
    scheduled_end = scheduled_start + timedelta(minutes=minutes)
    room_block_end = scheduled_end + timedelta(minutes=TURNOVER_BY_ROOM_CLASS[room["room_class"]])
    return minutes, scheduled_end, room_block_end


def check_temporal_gates(procedure_type, scheduled_start):
    """Rung 9 (business_temporal) for booking creation / reschedule / PATCH."""
    current = now()
    if scheduled_start <= current:
        raise_error(ERR_SCHEDULED_START_IN_PAST,
                    "scheduled_start must lie strictly in the future")
    lead = PREP_LEAD_HOURS[procedure_type["prep_protocol"]]
    if scheduled_start < current + timedelta(hours=lead):
        raise_error(ERR_PREP_LEAD_TIME_INSUFFICIENT,
                    f"prep_protocol {procedure_type['prep_protocol']} requires >= {lead}h lead")


def _room_candidates(room_id, exclude_booking_id=None):
    return [
        b for b in db["bookings"].values()
        if b["room_id"] == room_id
        and b["status"] in BLOCK_HOLDING_STATUSES
        and b["id"] != exclude_booking_id
    ]


def check_room_overlap_and_capacity(room, scheduled_start, room_block_end, exclude_booking_id=None):
    """Rung 10 (business_constraint): half-open overlap first, then day capacity."""
    candidates = _room_candidates(room["id"], exclude_booking_id)
    for c in candidates:
        if scheduled_start < c["room_block_end"] and room_block_end > c["scheduled_start"]:
            raise_error(ERR_ROOM_TIME_CONFLICT,
                        "half-open room block overlaps an existing committed booking")
    day = scheduled_start.date()
    committed = 0
    for c in candidates:
        if c["scheduled_start"].date() == day:
            committed += int((c["room_block_end"] - c["scheduled_start"]).total_seconds() // 60)
    new_block = int((room_block_end - scheduled_start).total_seconds() // 60)
    if committed + new_block > ROOM_DAY_CAPACITY_MINUTES:
        raise_error(ERR_ROOM_DAY_CAPACITY_EXCEEDED,
                        "committed room block minutes for the date would exceed 480")


def cancel_active_assignments(booking_id, reason=None):
    """Cascade: ASSIGNED/CONFIRMED assignments -> CANCELLED (minutes release is
    automatic because scheduled_minutes is computed from live statuses)."""
    for a in db["anesthesia_assignments"].values():
        if a["booking_id"] == booking_id and a["status"] in ("ASSIGNED", "CONFIRMED"):
            a["status"] = "CANCELLED"
            if reason is not None:
                a["cancel_reason"] = reason
            touch(a)


def complete_confirmed_assignments(booking_id):
    for a in db["anesthesia_assignments"].values():
        if a["booking_id"] == booking_id and a["status"] == "CONFIRMED":
            a["status"] = "COMPLETED"
            touch(a)


def release_scope_after_procedure(booking_id):
    """complete/abort: an ACTIVE usage sends its scope to AWAITING_REPROCESS."""
    from services.core import active_usage_for_booking
    usage = active_usage_for_booking(booking_id)
    if usage is None:
        return
    scope = db["scopes"].get(usage["scope_id"])
    if scope is not None and scope["status"] == "IN_USE":
        scope["status"] = "AWAITING_REPROCESS"
        scope["awaiting_reprocess_since"] = now()
        touch(scope)


def compute_actual_duration_minutes(booking):
    """procedure_occupancy_minutes actual variant: floor(elapsed seconds / 60)."""
    start = booking.get("actual_start")
    end = booking.get("actual_end")
    if start is None or end is None:
        return None
    return int((end - start).total_seconds() // 60)
