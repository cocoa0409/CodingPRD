"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the input fields the corresponding POST accepts,
with sensible defaults overridable via keyword arguments.
"""
from .constants import DEFAULT_RECEIVED_AT


def create_controller_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Controller",
        "jurisdiction": "GDPR",
        "dpo_email": "dpo@test.example",
    }
    defaults.update(overrides)
    return defaults


def create_data_subject_payload(controller_id, **overrides) -> dict:
    defaults = {
        "controller_id": controller_id,
        "email": "subject@test.example",
        "full_name": "Test Subject",
        "jurisdiction_residency": "EU",
    }
    defaults.update(overrides)
    return defaults


def create_processor_payload(controller_id, **overrides) -> dict:
    defaults = {
        "controller_id": controller_id,
        "name": "Test Processor",
        "notify_email": "notify@test.example",
    }
    defaults.update(overrides)
    return defaults


def create_consent_record_payload(data_subject_id, **overrides) -> dict:
    defaults = {
        "data_subject_id": data_subject_id,
        "purpose": "MARKETING",
    }
    defaults.update(overrides)
    return defaults


def create_legal_hold_payload(controller_id, data_subject_id, **overrides) -> dict:
    defaults = {
        "controller_id": controller_id,
        "data_subject_id": data_subject_id,
        "matter_reference": "MATTER-TEST",
        "data_categories": ["IDENTITY"],
    }
    defaults.update(overrides)
    return defaults


def create_dsar_request_payload(controller_id, data_subject_id, **overrides) -> dict:
    defaults = {
        "controller_id": controller_id,
        "data_subject_id": data_subject_id,
        "request_type": "ACCESS",
        "received_at": DEFAULT_RECEIVED_AT,
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(processor_id, **overrides) -> dict:
    defaults = {
        "processor_id": processor_id,
        "data_category": "IDENTITY",
        "record_count": 1,
        "confidence": "EXACT",
    }
    defaults.update(overrides)
    return defaults


def create_exemption_payload(**overrides) -> dict:
    defaults = {
        "data_category": "IDENTITY",
        "basis": "TRADE_SECRET",
    }
    defaults.update(overrides)
    return defaults
