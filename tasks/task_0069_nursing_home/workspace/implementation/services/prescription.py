"""Prescription business logic: activation safety, dispensing schedule,
suspend/resume/discontinue.
"""
import datetime as _dt

from clock import format_dt, iso_now, parse_date
from db import get_db
from errors import APIError
from helpers import touch
from services import audit


def generate_schedule(prescription):
    """Generate dispensing schedule slots: frequency_per_day per day across
    [starts_on, ends_on] inclusive. Slots evenly distributed in 24h.
    Returns a list of ISO8601 UTC strings.
    """
    f = int(prescription["frequency_per_day"])
    start = parse_date(prescription["starts_on"])
    end = parse_date(prescription["ends_on"])
    slots = []
    day = start
    while day <= end:
        if f <= 0:
            break
        # Distribute slots starting at 08:00 UTC, evenly across 24h/f
        interval_minutes = max(1, (24 * 60) // f)
        base = _dt.datetime.combine(day, _dt.time(8, 0, 0), tzinfo=_dt.timezone.utc)
        for i in range(f):
            slot_dt = base + _dt.timedelta(minutes=interval_minutes * i)
            slots.append(format_dt(slot_dt))
        day += _dt.timedelta(days=1)
    return slots


def activate(prescription, user_id, role):
    """PENDING_REVIEW -> ACTIVE with drug-interaction (priority 9) + allergy (10) gates."""
    db = get_db()
    prev = prescription["status"]
    if prev != "PENDING_REVIEW":
        raise APIError("ERR_INVALID_STATE",
                       f"Prescription is {prev}, expected PENDING_REVIEW", 409)
    elder = db.elders.get(prescription["elder_id"])
    if elder is None:
        raise APIError("ERR_INVALID_STATE", "Elder missing", 409)
    if elder.get("status") != "ADMITTED":
        raise APIError("ERR_INVALID_STATE", "Elder must be ADMITTED", 409)

    # Drug interaction (priority 9) — must come BEFORE allergy
    own_code = prescription["drug_code"]
    own_interacts = set(prescription.get("interacts_with_drug_codes") or [])
    for other in db.prescriptions.values():
        if (other["id"] != prescription["id"]
                and other["elder_id"] == elder["id"]
                and other["status"] == "ACTIVE"):
            other_codes = set(other.get("interacts_with_drug_codes") or [])
            if own_code in other_codes:
                raise APIError("ERR_DRUG_INTERACTION",
                               f"Conflicts with ACTIVE Prescription {other['id']}", 409)
            if other["drug_code"] in own_interacts:
                raise APIError("ERR_DRUG_INTERACTION",
                               f"Conflicts with ACTIVE Prescription {other['id']}", 409)

    # Allergy (priority 10)
    elder_allergies = set(elder.get("allergies") or [])
    contraind = set(prescription.get("contraindicated_allergens") or [])
    if elder_allergies & contraind:
        raise APIError("ERR_ALLERGY_CONFLICT",
                       "Elder allergies overlap prescription contraindications", 409)

    prescription["status"] = "ACTIVE"
    touch(prescription)
    schedule = generate_schedule(prescription)
    db.prescription_schedules[prescription["id"]] = schedule
    prescription["dispensing_schedule"] = schedule

    audit.log(role, user_id, "Prescription", prescription["id"],
              "ACTIVATE", prev, prescription["status"])


def suspend(prescription, user_id, role):
    prev = prescription["status"]
    if prev != "ACTIVE":
        raise APIError("ERR_INVALID_STATE",
                       f"Prescription is {prev}, expected ACTIVE", 409)
    prescription["status"] = "SUSPENDED"
    touch(prescription)
    audit.log(role, user_id, "Prescription", prescription["id"],
              "SUSPEND", prev, prescription["status"])


def resume(prescription, user_id, role):
    db = get_db()
    prev = prescription["status"]
    if prev != "SUSPENDED":
        raise APIError("ERR_INVALID_STATE",
                       f"Prescription is {prev}, expected SUSPENDED", 409)
    elder = db.elders.get(prescription["elder_id"])
    if elder is None or elder.get("status") != "ADMITTED":
        raise APIError("ERR_INVALID_STATE", "Elder must be ADMITTED to resume", 409)
    prescription["status"] = "ACTIVE"
    touch(prescription)
    audit.log(role, user_id, "Prescription", prescription["id"],
              "RESUME", prev, prescription["status"])


def discontinue(prescription, user_id, role):
    prev = prescription["status"]
    if prev not in ("PENDING_REVIEW", "ACTIVE", "SUSPENDED"):
        raise APIError("ERR_INVALID_STATE",
                       f"Prescription is {prev}, cannot DISCONTINUE", 409)
    prescription["status"] = "DISCONTINUED"
    touch(prescription)
    # Only ACTIVE -> DISCONTINUED writes an audit row per PRD 3.4
    if prev == "ACTIVE":
        audit.log(role, user_id, "Prescription", prescription["id"],
                  "DISCONTINUE", prev, prescription["status"])
