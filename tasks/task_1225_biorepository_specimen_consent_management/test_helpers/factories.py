"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS

_counter = {"n": 0}


def _unique(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}"


def create_donor_payload(**overrides) -> dict:
    defaults = {"donor_reference_code": _unique("D")}
    defaults.update(overrides)
    return defaults


def create_consent_record_payload(**overrides) -> dict:
    defaults = {
        "permitted_uses": ["GENERAL_RESEARCH"],
        "effective_from": TEST_DEFAULTS["CONSENT_EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_collection_kit_payload(**overrides) -> dict:
    defaults = {
        "kit_type": "BLOOD",
        "expires_at": TEST_DEFAULTS["KIT_EXPIRES_AT_FAR"],
    }
    defaults.update(overrides)
    return defaults


def create_specimen_payload(**overrides) -> dict:
    defaults = {
        "specimen_type": "BLOOD",
        "initial_volume_ml": 100.0,
        "collected_at": TEST_DEFAULTS["COLLECTED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_aliquot_payload(**overrides) -> dict:
    defaults = {"initial_volume_ml": 40.0}
    defaults.update(overrides)
    return defaults


def create_storage_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_code": _unique("FRZ"),
        "setpoint_c": TEST_DEFAULTS["SETPOINT_C"],
    }
    defaults.update(overrides)
    return defaults


def create_storage_slot_payload(**overrides) -> dict:
    defaults = {
        "slot_code": "A1",
        "capacity_ml": TEST_DEFAULTS["SLOT_CAPACITY_ML"],
    }
    defaults.update(overrides)
    return defaults


def create_slot_reservation_payload(**overrides) -> dict:
    defaults = {
        "starts_at": "2026-06-01T10:00:00Z",
        "ends_at": "2026-06-01T12:00:00Z",
        "purpose": "MAINTENANCE",
    }
    defaults.update(overrides)
    return defaults


def create_temperature_reading_payload(**overrides) -> dict:
    defaults = {
        "recorded_at": TEST_DEFAULTS["CLOCK_START_ISO"],
        "temp_c": -80.0,
    }
    defaults.update(overrides)
    return defaults


def create_sample_request_payload(**overrides) -> dict:
    defaults = {
        "title": _unique("RQ"),
        "required_uses": ["GENERAL_RESEARCH"],
        "specimen_type": "BLOOD",
        "volume_needed_ml": 40.0,
    }
    defaults.update(overrides)
    return defaults


def create_vote_payload(**overrides) -> dict:
    defaults = {
        "decision": "APPROVE",
        "rationale": TEST_DEFAULTS["VOTE_RATIONALE_APPROVE"],
    }
    defaults.update(overrides)
    return defaults


def create_sharing_agreement_payload(**overrides) -> dict:
    defaults = {
        "recipient_institution": _unique("Uni"),
        "scope_uses": ["GENERAL_RESEARCH"],
        "total_committed_volume_ml": 1000.0,
        "effective_from": TEST_DEFAULTS["AGREEMENT_EFFECTIVE_FROM"],
        "effective_to": TEST_DEFAULTS["AGREEMENT_EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_deidentification_key_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_key_access_grant_payload(**overrides) -> dict:
    defaults = {
        "grantee_user_id": "officer-a",
        "starts_at": "2026-06-01T09:00:00Z",
        "ends_at": "2026-06-01T17:00:00Z",
        "purpose": "audit follow-up",
    }
    defaults.update(overrides)
    return defaults


def create_destruction_order_payload(**overrides) -> dict:
    defaults = {"reason": "QUALITY_FAILURE"}
    defaults.update(overrides)
    return defaults
