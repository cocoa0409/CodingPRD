"""Payload factories — one per entity, input fields only."""
from .constants import DEFAULT_PER_BENEFICIARY_CAP_CENTS

CORE_IDG = ["PHYSICIAN", "NURSE", "SOCIAL_WORK", "COUNSELOR"]


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Hospice",
        "cap_year_start": "2026-01-01T00:00:00Z",
        "per_beneficiary_cap_cents": DEFAULT_PER_BENEFICIARY_CAP_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_physician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr Test",
        "is_medical_director": False,
    }
    defaults.update(overrides)
    return defaults


def create_election_payload(provider_id: str, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "patient_name": "Test Patient",
        "election_date": "2026-01-01T00:00:00Z",
        "attending_physician_id": "ext-att-default",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(election_id: str, certifying_physician_id: str,
                                 expected_election_version: int, **overrides) -> dict:
    defaults = {
        "election_id": election_id,
        "period_sequence": 1,
        "certifying_physician_id": certifying_physician_id,
        "narrative_present": True,
        "expected_election_version": expected_election_version,
        "commit": True,
    }
    defaults.update(overrides)
    return defaults


def create_care_plan_payload(election_id: str, expected_election_version: int, **overrides) -> dict:
    defaults = {
        "election_id": election_id,
        "idg_members": list(CORE_IDG),
        "expected_election_version": expected_election_version,
    }
    defaults.update(overrides)
    return defaults


def create_care_day_payload(election_id: str, service_date: str, level_of_care: str,
                            high_intensity: bool = False, **overrides) -> dict:
    defaults = {
        "election_id": election_id,
        "service_date": service_date,
        "level_of_care": level_of_care,
        "high_intensity": high_intensity,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_item_payload(election_id: str, care_plan_id: str,
                                 item_type: str = "MEDICATION",
                                 related_to_terminal_dx: bool = True, **overrides) -> dict:
    defaults = {
        "election_id": election_id,
        "care_plan_id": care_plan_id,
        "item_type": item_type,
        "related_to_terminal_dx": related_to_terminal_dx,
    }
    defaults.update(overrides)
    return defaults


def create_bereavement_case_payload(election_id: str, enrolled_date: str, **overrides) -> dict:
    defaults = {
        "election_id": election_id,
        "enrolled_date": enrolled_date,
    }
    defaults.update(overrides)
    return defaults
