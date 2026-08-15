"""Payload factories — one per entity, input fields only.

Field names follow the PRD narratives exactly; optional fields are added
only when explicitly supplied.
"""
from .constants import (
    DEFAULT_CLASS_DATE,
    DEFAULT_MEDICAL_ISSUED_AT,
    TEST_DEFAULTS,
)

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_applicant_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Test Applicant {n}",
        "email": f"applicant{n}@example.com",
        "license_number": f"LIC{n:05d}",
        "total_flight_hours": TEST_DEFAULTS["TOTAL_FLIGHT_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_records_request_payload(applicant_id, request_type="PRIA") -> dict:
    return {"applicant_id": applicant_id, "request_type": request_type}


def create_equipment_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "code": f"EQ{n:03d}",
        "name": f"Fleet {n}",
        "simulator_cost_per_hour_cents": TEST_DEFAULTS["SIMULATOR_COST_PER_HOUR_CENTS"],
        "ioe_hours_required": TEST_DEFAULTS["IOE_HOURS_REQUIRED"],
    }
    # landings_required_90d is optional (server default applies when omitted),
    # so it is included only when the caller asks for it.
    if "landings_required_90d" in overrides:
        defaults["landings_required_90d"] = overrides.pop("landings_required_90d")
    defaults.update(overrides)
    return defaults


def create_training_class_payload(equipment_id, **overrides) -> dict:
    defaults = {
        "equipment_id": equipment_id,
        "class_date": DEFAULT_CLASS_DATE,
        "seat_capacity": TEST_DEFAULTS["SEAT_CAPACITY"],
        "base_attrition_rate": TEST_DEFAULTS["BASE_ATTRITION_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(applicant_id, training_class_id,
                              expected_training_class_version) -> dict:
    return {
        "applicant_id": applicant_id,
        "training_class_id": training_class_id,
        "expected_training_class_version": expected_training_class_version,
    }


def create_instructor_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Instructor {n}",
        "instructor_type": "GROUND",
        "daily_max_sessions": TEST_DEFAULTS["DAILY_MAX_SESSIONS"],
    }
    defaults.update(overrides)
    return defaults


def create_simulator_slot_payload(equipment_id, start_at, end_at) -> dict:
    return {"equipment_id": equipment_id, "start_at": start_at, "end_at": end_at}


def create_training_event_payload(enrollment_id, instructor_id, phase,
                                  event_type, scheduled_start, scheduled_end,
                                  simulator_slot_id=None) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "instructor_id": instructor_id,
        "phase": phase,
        "event_type": event_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    if simulator_slot_id is not None:
        payload["simulator_slot_id"] = simulator_slot_id
    return payload


def create_checkride_payload(enrollment_id, check_airman_id, scheduled_at,
                             ride_type="PRACTICAL") -> dict:
    return {
        "enrollment_id": enrollment_id,
        "check_airman_id": check_airman_id,
        "ride_type": ride_type,
        "scheduled_at": scheduled_at,
    }


def create_qualification_payload(applicant_id, equipment_id) -> dict:
    return {"applicant_id": applicant_id, "equipment_id": equipment_id}


def create_flight_activity_payload(qualification_id, activity_date, landings,
                                   hours, activity_type="REVENUE") -> dict:
    return {
        "qualification_id": qualification_id,
        "activity_date": activity_date,
        "landings": landings,
        "hours": hours,
        "activity_type": activity_type,
    }


def create_medical_certificate_payload(applicant_id, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "cert_class": "FIRST",
        "issued_at": DEFAULT_MEDICAL_ISSUED_AT,
        "pilot_age_at_issue": TEST_DEFAULTS["PILOT_AGE_AT_ISSUE"],
    }
    defaults.update(overrides)
    return defaults


def create_bid_period_payload(equipment_id, **overrides) -> dict:
    defaults = {
        "equipment_id": equipment_id,
        "opens_at": "2026-07-01T00:00:00Z",
        "closes_at": "2026-08-20T00:00:00Z",
        "seats_available": 1,
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(bid_period_id, applicant_id, preference_rank=1) -> dict:
    return {
        "bid_period_id": bid_period_id,
        "applicant_id": applicant_id,
        "preference_rank": preference_rank,
    }
