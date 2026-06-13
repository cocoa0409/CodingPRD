"""Scheduling-safety checks and appointment creation (PRD §3.5, §3.6)."""
from datetime import timedelta

import db
from errors import err
from models import new_record, touch, _parse_iso
from services.calculations import CAP_COUNTING_VISIT_TYPES


def _interval(appt):
    return _parse_iso(appt["scheduled_start"]), _parse_iso(appt["scheduled_end"])


def check_resources(provider, room):
    """Priority 11: assigned provider ACTIVE and room OPEN."""
    if provider["status"] != "ACTIVE" or room["status"] != "OPEN":
        raise err("ERR_RESOURCE_UNAVAILABLE", "Assigned provider or room is unavailable")


def check_room_type(visit_type, room):
    """Priority 12: X_RAY requires an IMAGING room."""
    if visit_type == "X_RAY" and room["room_type"] != "IMAGING":
        raise err("ERR_ROOM_TYPE_MISMATCH", "X_RAY visit requires an IMAGING room")


def check_provider_conflict(provider_id, start_dt, end_dt, exclude_id=None):
    """Priority 13: half-open overlap against BOOKED/CHECKED_IN appts for the
    same provider. Adjacency (end == start) does not conflict.
    """
    for a in db.appointments.values():
        if a["id"] == exclude_id:
            continue
        if a["provider_id"] != provider_id:
            continue
        if a["attendance_status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        a_start, a_end = _interval(a)
        # half-open [start, end) intersects [a_start, a_end)
        if start_dt < a_end and a_start < end_dt:
            raise err("ERR_PROVIDER_DOUBLE_BOOKED", "Provider is double-booked")


def check_room_conflict(room, start_dt, end_dt, exclude_id=None):
    """Priority 14: new start must be >= prior room appt end + buffer; a
    non-zero buffer makes adjacency insufficient.
    """
    buffer_min = room.get("turnover_buffer_minutes", 0) or 0
    buffer = timedelta(minutes=buffer_min)
    for a in db.appointments.values():
        if a["id"] == exclude_id:
            continue
        if a["treatment_room_id"] != room["id"]:
            continue
        if a["attendance_status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        a_start, a_end = _interval(a)
        # Both directions: the two appointments plus buffer must not overlap.
        # New appt must start at/after a_end + buffer, OR end at/before a_start - buffer.
        if start_dt >= a_end + buffer:
            continue
        if end_dt + buffer <= a_start:
            continue
        raise err("ERR_ROOM_BUFFER_CONFLICT", "Room turnover buffer conflict")


def reserve_cap(patient, visit_type, policy):
    """Priority 16 cap check (PRD §3.6). Returns counts_against_cap bool.

    For INSURANCE patients booking a cap-counting visit_type, projects usage and
    rejects with ERR_VISIT_CAP_EXCEEDED on strict overflow; otherwise reserves a
    slot. Mutates the policy's visits_reserved when reserved.
    """
    if patient["payer_mode"] != "INSURANCE":
        return False
    if visit_type not in CAP_COUNTING_VISIT_TYPES:
        return False
    projected = policy["visits_reserved"] + policy["visits_committed"] + 1
    if projected > policy["annual_visit_cap"]:
        raise err("ERR_VISIT_CAP_EXCEEDED", "Insurance visit cap exceeded")
    policy["visits_reserved"] += 1
    touch(policy)
    return True


def create_appointment(patient, body, provider, room, policy,
                       scheduled_start_iso, duration_minutes,
                       plan_phase_id=None, appointment_series_id=None,
                       replaces_appointment_id=None, insurance_policy_id=None):
    """Create one BOOKED appointment after all scheduling checks have passed
    and a cap slot (if any) has been reserved by the caller.
    """
    start_dt = _parse_iso(scheduled_start_iso)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    rec = new_record({
        "patient_id": patient["id"],
        "appointment_series_id": appointment_series_id,
        "plan_phase_id": plan_phase_id,
        "provider_id": provider["id"],
        "treatment_room_id": room["id"],
        "insurance_policy_id": insurance_policy_id,
        "visit_type": body["visit_type"] if "visit_type" in body else body.get("visit_type"),
        "replaces_appointment_id": replaces_appointment_id,
        "scheduled_start": scheduled_start_iso,
        "scheduled_end": _iso(end_dt),
        "duration_minutes": duration_minutes,
        "counts_against_cap": False,
        "patient_responsibility_cents": 0,
        "insurance_paid_cents": 0,
        "no_show_fee_cents": 0,
        "attendance_status": "BOOKED",
        "billing_status": "UNBILLED",
    })
    return rec


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def release_cap_for_appointment(appt):
    """Release a reserved cap slot for a still-BOOKED/CHECKED_IN appointment."""
    if appt.get("counts_against_cap"):
        policy = db.insurance_policies.get(appt.get("insurance_policy_id"))
        if policy:
            policy["visits_reserved"] = max(0, policy["visits_reserved"] - 1)
            touch(policy)
