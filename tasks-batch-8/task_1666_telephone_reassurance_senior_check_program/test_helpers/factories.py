"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import (
    AGREEMENT_VALID_UNTIL,
    MON_0803,
    POLICY_VERSION,
    TRAINING_COMPLETED_AT,
    TRAINING_VALID_UNTIL,
)


def create_program_payload(**overrides) -> dict:
    """Program creation: name, total_capacity, current_policy_version required;
    the eight protocol knobs optional (PRD §3.1)."""
    defaults = {
        "name": "AAA Senior Check-In",
        "total_capacity": 10,
        "current_policy_version": POLICY_VERSION,
        "max_reserve_slots": 0,
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(**overrides) -> dict:
    """Participant intake payload (PRD §3.2). Defaults produce a LOW-tier
    applicant (score 5: one chronic condition, no other points)."""
    defaults = {
        "full_name": "Test Participant",
        "date_of_birth": "1952-01-01",
        "phone": "555-0100",
        "address": "1 Test Rd",
        "referral_source": "SELF",
        "age_band": "AGE_65_74",
        "lives_alone": False,
        "mobility": "NONE",
        "cognitive_concern": False,
        "chronic_conditions_count": 1,
        "recent_hospitalization": False,
        "recent_bereavement": False,
    }
    defaults.update(overrides)
    return defaults


def create_emergency_contact_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Kin Contact",
        "phone": "555-9900",
        "relationship": "son",
        "contact_rank": "PRIMARY",
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Volunteer",
        "phone": "555-0200",
    }
    defaults.update(overrides)
    return defaults


def create_availability_window_payload(**overrides) -> dict:
    defaults = {
        "weekday": "MON",
        "window_start": "08:00",
        "window_end": "17:00",
        "effective_from": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(**overrides) -> dict:
    defaults = {
        "module": "SAFETY_PROTOCOL",
        "completed_at": TRAINING_COMPLETED_AT,
        "valid_until": TRAINING_VALID_UNTIL,
    }
    defaults.update(overrides)
    return defaults


def create_confidentiality_agreement_payload(**overrides) -> dict:
    defaults = {
        "policy_version": POLICY_VERSION,
        "valid_until": AGREEMENT_VALID_UNTIL,
    }
    defaults.update(overrides)
    return defaults


def create_call_schedule_payload(**overrides) -> dict:
    defaults = {
        "weekday": "MON",
        "window_start": "09:00",
        "window_end": "11:00",
    }
    defaults.update(overrides)
    return defaults


def create_call_assignment_payload(**overrides) -> dict:
    defaults = {
        "participant_id": None,
        "scheduled_date": MON_0803,
        "window_start": "09:00",
        "window_end": "09:30",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_call_log_payload(**overrides) -> dict:
    defaults = {
        "called_at": "2026-08-03T09:05:00Z",
        "duration_seconds": 300,
        "outcome": "REACHED_OK",
    }
    defaults.update(overrides)
    return defaults


def create_escalation_payload(**overrides) -> dict:
    defaults = {
        "participant_id": None,
        "trigger_type": "MANUAL",
        "expected_participant_version": None,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_service_referral_payload(**overrides) -> dict:
    defaults = {
        "participant_id": None,
        "service_type": "MEALS",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def issue_survey_payload(**overrides) -> dict:
    defaults = {"period_month": "2026-08"}
    defaults.update(overrides)
    return defaults


def return_survey_payload(**overrides) -> dict:
    defaults = {"items": [4, 3, 5, 2, 4]}
    defaults.update(overrides)
    return defaults
