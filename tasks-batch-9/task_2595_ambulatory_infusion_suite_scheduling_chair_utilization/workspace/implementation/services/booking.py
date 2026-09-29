"""Window sizing (PRD 3.4) and the staggered-start selector (PRD 3.5)."""

from decimal import Decimal

import db
from db import rows
from errors import ApiError
from services.derive import COMMITTED_STATUSES

TIER_ESCALATION = {"LOW": 0, "MID": 30, "HIGH": 60}


def dose_mg_for(plan, patient):
    dose = Decimal(str(plan["dose_mg_per_kg"])) * Decimal(str(patient["weight_kg"]))
    return db.rhu(dose, 1)


def tier_for_dose(dose_mg):
    if dose_mg <= Decimal("500"):
        return "LOW"
    if dose_mg <= Decimal("1000"):
        return "MID"
    return "HIGH"


def build_window(plan, patient, template, extension_minutes=0):
    """The six-step window build; raises ERR_TEMPLATE_TIER_MISMATCH on a tier clash."""
    dose_mg = dose_mg_for(plan, patient)
    tier = tier_for_dose(dose_mg)
    escalation = TIER_ESCALATION[tier]
    if template["dose_tier"] != tier:
        raise ApiError("ERR_TEMPLATE_TIER_MISMATCH")
    admin_minutes = max(
        int(template["min_admin_minutes"]), int(template["base_admin_minutes"]) + escalation
    )
    premed_minutes = 0 if plan.get("premed_waived") else int(template["premed_minutes"])
    if plan.get("first_dose_completed"):
        base_observation = int(template["observation_minutes_subsequent"])
    else:
        base_observation = int(template["observation_minutes_first"])
    observation_minutes = base_observation + int(extension_minutes or 0)
    chair_minutes = premed_minutes + admin_minutes + observation_minutes
    acuity_points = int(template["acuity_points"]) + (0 if plan.get("first_dose_completed") else 1)
    return {
        "dose_mg": dose_mg,
        "dose_tier": tier,
        "premed_minutes": premed_minutes,
        "admin_minutes": admin_minutes,
        "observation_minutes": observation_minutes,
        "observation_extension_minutes": int(extension_minutes or 0),
        "chair_minutes": chair_minutes,
        "acuity_points": acuity_points,
    }


def snap_up(value, grid):
    grid = int(grid)
    if grid <= 0:
        return int(value)
    return -((-int(value)) // grid) * grid


def check_operating_hours(center, requested_start_minute, chair_minutes):
    """Returns the grid-snapped start, or raises ERR_OUTSIDE_OPERATING_HOURS."""
    open_minute = int(center["open_minute"])
    close_minute = int(center["close_minute"])
    if not (open_minute <= int(requested_start_minute) < close_minute):
        raise ApiError("ERR_OUTSIDE_OPERATING_HOURS")
    snapped = snap_up(requested_start_minute, center["stagger_grid_minutes"])
    if snapped < open_minute or snapped + int(chair_minutes) > close_minute:
        raise ApiError("ERR_OUTSIDE_OPERATING_HOURS")
    return snapped


def candidate_starts(center, snapped, chair_minutes, booking_class):
    grid = int(center["stagger_grid_minutes"])
    open_minute = int(center["open_minute"])
    close_minute = int(center["close_minute"])
    if booking_class == "URGENT":
        raw = [snapped]
    else:
        raw = [snapped + k * grid for k in range(9)]
    return [
        start
        for start in raw
        if start >= open_minute and start + int(chair_minutes) <= close_minute
    ]


def _live_visits(service_date, exclude_ids):
    return [
        appointment
        for appointment in rows("appointments")
        if appointment.get("service_date") == service_date
        and appointment["schedule_status"] in COMMITTED_STATUSES
        and appointment["id"] not in exclude_ids
    ]


def chair_committed_minutes(chair_id, exclude_ids):
    total = 0
    for appointment in rows("appointments"):
        if appointment.get("chair_id") != chair_id:
            continue
        if appointment["schedule_status"] not in COMMITTED_STATUSES:
            continue
        if appointment["id"] in exclude_ids:
            continue
        total += int(appointment.get("chair_minutes") or 0)
    return total


def nurse_assigned_points(nurse_id, exclude_ids):
    total = 0
    for appointment in rows("appointments"):
        if appointment.get("nurse_id") != nurse_id:
            continue
        if appointment["schedule_status"] not in COMMITTED_STATUSES:
            continue
        if appointment["id"] in exclude_ids:
            continue
        total += int(appointment.get("acuity_points") or 0)
    return total


def chair_is_free(chair, start, chair_minutes, buffer_minutes, day_visits):
    for other in day_visits:
        if other.get("chair_id") != chair["id"]:
            continue
        other_start = int(other.get("start_minute") or 0)
        other_end = int(other.get("end_minute") or 0)
        if start < other_end + buffer_minutes and other_start < start + chair_minutes + buffer_minutes:
            return False
    return True


def slot_indexes(open_minute, slot_width, start, end):
    """Indexes of the acuity slots the half-open occupancy touches."""
    if slot_width <= 0 or end <= start:
        return []
    first = (start - open_minute) // slot_width
    last = (end - 1 - open_minute) // slot_width
    return list(range(first, last + 1))


def nurse_slot_load(nurse_id, slot_start, slot_end, day_visits):
    total = 0
    for appointment in day_visits:
        if appointment.get("nurse_id") != nurse_id:
            continue
        start = int(appointment.get("start_minute") or 0)
        end = int(appointment.get("end_minute") or 0)
        if start < slot_end and slot_start < end:
            total += int(appointment.get("acuity_points") or 0)
    return total


def urgent_reserve_claimed(center_id, service_date):
    return sum(
        1
        for appointment in rows("appointments")
        if appointment.get("center_id") == center_id
        and appointment.get("service_date") == service_date
        and appointment.get("booking_class") == "URGENT"
        and appointment["schedule_status"] in COMMITTED_STATUSES
        and appointment.get("chair_id") is not None
        and (db.get("chairs", appointment["chair_id"]) or {}).get("reserved_for_urgent")
    )


def check_urgent_reserve_limit(center_id, service_date):
    reserved_chairs = sum(
        1 for chair in rows("chairs")
        if chair.get("center_id") == center_id and chair.get("reserved_for_urgent")
    )
    if urgent_reserve_claimed(center_id, service_date) >= reserved_chairs:
        raise ApiError("ERR_URGENT_RESERVE_LIMIT")


def select_slot(center, service_date, chair_minutes, acuity_points, booking_class,
                snapped_start, exclude_ids=()):
    """Deterministically choose (start_minute, chair, nurse) or raise the capacity refusal."""
    exclude_ids = set(exclude_ids)
    buffer_minutes = int(center["turnover_buffer_minutes"])
    slot_width = int(center["acuity_slot_minutes"])
    open_minute = int(center["open_minute"])
    chair_minutes = int(chair_minutes)
    day_visits = _live_visits(service_date, exclude_ids)

    center_chairs = [
        chair for chair in rows("chairs")
        if chair.get("center_id") == center["id"]
        and chair.get("status") == "AVAILABLE"
        and (booking_class == "URGENT" or not chair.get("reserved_for_urgent"))
    ]
    center_nurses = [
        nurse for nurse in rows("nurses")
        if nurse.get("center_id") == center["id"] and nurse.get("status") == "ACTIVE"
    ]

    any_chair = False
    any_nurse_on_shift = False

    for start in candidate_starts(center, snapped_start, chair_minutes, booking_class):
        end = start + chair_minutes
        eligible_chairs = [
            chair for chair in center_chairs
            if chair_is_free(chair, start, chair_minutes, buffer_minutes, day_visits)
        ]
        if not eligible_chairs:
            continue
        any_chair = True

        on_shift = [
            nurse for nurse in center_nurses
            if int(nurse["shift_start_minute"]) <= start
            and end <= int(nurse["shift_end_minute"])
        ]
        if not on_shift:
            continue
        any_nurse_on_shift = True

        indexes = slot_indexes(open_minute, slot_width, start, end)
        acuity_ok = []
        for nurse in on_shift:
            capacity = int(nurse["acuity_capacity_points"])
            fits = True
            for index in indexes:
                slot_start = open_minute + index * slot_width
                slot_end = slot_start + slot_width
                load = nurse_slot_load(nurse["id"], slot_start, slot_end, day_visits)
                if load + int(acuity_points) > capacity:
                    fits = False
                    break
            if fits:
                acuity_ok.append(nurse)
        if not acuity_ok:
            continue

        if booking_class == "URGENT":
            eligible_chairs.sort(
                key=lambda c: (
                    0 if c.get("reserved_for_urgent") else 1,
                    chair_committed_minutes(c["id"], exclude_ids),
                    c["label"],
                )
            )
        else:
            eligible_chairs.sort(
                key=lambda c: (chair_committed_minutes(c["id"], exclude_ids), c["label"])
            )
        acuity_ok.sort(key=lambda n: (nurse_assigned_points(n["id"], exclude_ids), n["_seq"]))
        return start, eligible_chairs[0], acuity_ok[0]

    if not any_chair:
        if booking_class == "URGENT":
            raise ApiError("ERR_URGENT_RESERVE_UNAVAILABLE")
        raise ApiError("ERR_NO_CHAIR_CAPACITY")
    if not any_nurse_on_shift:
        raise ApiError("ERR_NO_NURSE_ON_SHIFT")
    raise ApiError("ERR_NURSE_ACUITY_EXCEEDED")
