"""Minority computation (PRD §3.1).

`is_minor_at_intake` is true when the patient's age at the moment the case's
intake was captured is < 18, derived from date_of_birth and the earliest
IntakeRecord.captured_at for that case. Defaults to false until an intake exists.
"""
from datetime import datetime

from clock import parse_iso8601
from db import db


def _parse_dob(dob_str):
    try:
        y, m, d = (int(x) for x in dob_str.split("-"))
        return y, m, d
    except (ValueError, AttributeError):
        return None


def age_at(dob_str, instant_dt):
    """Whole-years age of someone born dob_str at the datetime instant_dt."""
    parsed = _parse_dob(dob_str)
    if parsed is None:
        return None
    y, m, d = parsed
    age = instant_dt.year - y
    if (instant_dt.month, instant_dt.day) < (m, d):
        age -= 1
    return age


def earliest_intake_for_case(case_id):
    records = [r for r in db.intake_records.values() if r["case_id"] == case_id]
    if not records:
        return None
    return min(records, key=lambda r: (r["captured_at"], r["_seq"]))


def is_minor_for_case(case):
    """True when the patient was a minor at the case's (earliest) intake capture."""
    intake = earliest_intake_for_case(case["id"])
    if intake is None:
        return False
    patient = db.patients.get(case["patient_id"])
    if patient is None:
        return False
    captured = parse_iso8601(intake["captured_at"])
    if captured is None:
        return False
    age = age_at(patient["date_of_birth"], captured)
    if age is None:
        return False
    return age < 18
