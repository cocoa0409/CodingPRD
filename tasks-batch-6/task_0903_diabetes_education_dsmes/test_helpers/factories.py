"""Payload factories — one per entity, input fields only.

Each factory supplies sensible defaults and accepts **overrides. Identifier-like
fields (mrn, npi, serial_number) are made unique per-call to avoid accidental
collisions within a single test.
"""
import uuid


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def create_program_payload(**overrides) -> dict:
    payload = {
        "name": "Test DSMES Program",
        "accreditation_body": "ADA",
    }
    payload.update(overrides)
    return payload


def create_curriculum_payload(**overrides) -> dict:
    payload = {
        "name": "Type 2 Core Curriculum",
        "diabetes_type_focus": "TYPE_2",
        "required_hours": 10.0,
        "module_count": 8,
    }
    payload.update(overrides)
    return payload


def create_patient_payload(**overrides) -> dict:
    payload = {
        "mrn": _uniq("MRN"),
        "full_name": "Test Patient",
        "date_of_birth": "1970-01-01",
        "diabetes_type": "TYPE_2",
        "payer": "MEDICARE",
        "baseline_a1c": 8.0,
    }
    payload.update(overrides)
    return payload


def create_dietitian_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Dietitian",
        "npi": _uniq("NPI"),
        "credential": "RD",
    }
    payload.update(overrides)
    return payload


def create_referral_payload(program_id, patient_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "patient_id": patient_id,
        "referring_provider_npi": _uniq("REFNPI"),
        "referral_reason": "POOR_CONTROL",
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(referral_id, curriculum_id, **overrides) -> dict:
    payload = {
        "referral_id": referral_id,
        "curriculum_id": curriculum_id,
    }
    payload.update(overrides)
    return payload


def create_session_payload(enrollment_id, dietitian_id, scheduled_start, scheduled_end,
                           expected_enrollment_version, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "dietitian_id": dietitian_id,
        "modality": "INDIVIDUAL",
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "expected_enrollment_version": expected_enrollment_version,
    }
    payload.update(overrides)
    return payload


def create_group_class_payload(curriculum_id, dietitian_id, scheduled_start, scheduled_end,
                               **overrides) -> dict:
    payload = {
        "curriculum_id": curriculum_id,
        "dietitian_id": dietitian_id,
        "room_id": "ROOM-1",
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "capacity": 5,
        "topic": "Nutrition Basics",
    }
    payload.update(overrides)
    return payload


def reserve_seat_payload(enrollment_id, expected_group_class_version, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "expected_group_class_version": expected_group_class_version,
    }
    payload.update(overrides)
    return payload


def create_device_enrollment_payload(enrollment_id, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "device_type": "CGM",
        "serial_number": _uniq("SN"),
    }
    payload.update(overrides)
    return payload


def create_reading_payload(glucose_mgdl, measured_at, **overrides) -> dict:
    payload = {
        "glucose_mgdl": glucose_mgdl,
        "measured_at": measured_at,
    }
    payload.update(overrides)
    return payload


def create_care_plan_payload(enrollment_id, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "goal_description": "Lower A1c below target",
        "target_a1c": 7.0,
    }
    payload.update(overrides)
    return payload
