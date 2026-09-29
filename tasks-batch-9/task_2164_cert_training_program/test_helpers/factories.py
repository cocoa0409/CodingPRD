"""Payload factories - one per entity, carrying only client-supplied fields."""

from .constants import TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    payload = {
        "name": "Riverside CERT",
        "sponsor_agency": "Riverside OES",
        "jurisdiction_code": "CA-RIV-01",
        "equipment_budget_cents": TEST_DEFAULTS["PROGRAM_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_cohort_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "cohort_code": "C-2026A",
        "seat_capacity": TEST_DEFAULTS["SEAT_CAPACITY"],
        "session_window_start": TEST_DEFAULTS["COHORT_WINDOW_START"],
        "session_window_end": TEST_DEFAULTS["COHORT_WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def create_curriculum_module_payload(**overrides) -> dict:
    payload = {
        "module_code": "CERT-101",
        "title": "Disaster Preparedness",
        "contact_hours": 2.5,
        "sequence_index": 1,
    }
    payload.update(overrides)
    return payload


def create_facility_payload(**overrides) -> dict:
    payload = {
        "name": "Riverside EOC",
        "room_code": "EOC-A",
        "capacity_seats": TEST_DEFAULTS["FACILITY_CAPACITY"],
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_instructor_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ines Ruiz",
        "certification_expires_on": TEST_DEFAULTS["INSTRUCTOR_CERT_EXPIRY"],
        "max_daily_contact_hours": TEST_DEFAULTS["INSTRUCTOR_MAX_DAILY_HOURS"],
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_class_session_payload(cohort_id, module_id, facility_id, instructor_id,
                                 starts_at, **overrides) -> dict:
    payload = {
        "cohort_id": cohort_id,
        "module_id": module_id,
        "facility_id": facility_id,
        "instructor_id": instructor_id,
        "starts_at": starts_at,
    }
    payload.update(overrides)
    return payload


def create_trainee_payload(program_id, cohort_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "cohort_id": cohort_id,
        "full_name": "Tara Nolan",
        "email": "tara@riverside.example",
        "deployment_hold": False,
    }
    payload.update(overrides)
    return payload


def create_module_completion_payload(trainee_id, class_session_id,
                                     attendance_minutes, **overrides) -> dict:
    payload = {
        "trainee_id": trainee_id,
        "class_session_id": class_session_id,
        "attendance_minutes": attendance_minutes,
    }
    payload.update(overrides)
    return payload


def create_equipment_asset_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "asset_tag": "BP-0001",
        "kit_type": "BACKPACK_STANDARD",
        "unit_value_cents": 17700,
    }
    payload.update(overrides)
    return payload


def create_equipment_issuance_payload(trainee_id, kit_type,
                                      expected_program_version, **overrides) -> dict:
    payload = {
        "trainee_id": trainee_id,
        "kit_type": kit_type,
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload


def create_exercise_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "title": "Drill 1",
        "exercise_type": "FUNCTIONAL",
        "starts_at": "2026-09-01T08:00:00Z",
        "ends_at": "2026-09-01T12:00:00Z",
        "base_credit_hours": 4.0,
    }
    payload.update(overrides)
    return payload


def create_exercise_participation_payload(exercise_id, trainee_id,
                                          role_played="LOGISTICS", **overrides) -> dict:
    payload = {
        "exercise_id": exercise_id,
        "trainee_id": trainee_id,
        "role_played": role_played,
    }
    payload.update(overrides)
    return payload


def create_activation_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "incident_number": "INC-2026-001",
        "requesting_agency": "County OES",
        "severity": "ROUTINE",
        "requested_responders": 1,
    }
    payload.update(overrides)
    return payload
