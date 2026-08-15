"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
from .constants import (
    DEFAULT_CERT_EXPIRY,
    DEFAULT_EXEC_END,
    DEFAULT_EXEC_START,
    DEFAULT_ISSUED_AT,
    MEETING_DAY,
    REHEARSAL_DAY,
)

DEFAULTS = {
    "PRODUCTION_NAME": "Test Production",
    "PRODUCTION_BUDGET": 10000000,
    "DECLARED_EXPOSURE": 50000000,
    "SEQUENCE_NAME": "Test Sequence",
    "HAZARD_CLASS": "FIGHT",
    "RISK_CATEGORY": "LOW",
    "PERFORMER_FIRST": "Stunt",
    "PERFORMER_LAST": "Performer",
    "DAY_RATE": 150000,
    "UNION_STATUS": "NON_UNION",
    "DISCIPLINE": "FIGHT",
    "CERT_LEVEL": "ADVANCED",
    "FACILITY": "Stage 1",
    "MEETING_FACILITY": "Stage 2",
    "EQUIPMENT_NAME": "Rig",
    "EQUIPMENT_TYPE": "RIGGING",
    "SERIAL": "SN-001",
    "INSPECTION_INTERVAL_HOURS": 72,
    "PERMIT_TYPE": "PYROTECHNICS",
    "JURISDICTION": "LA County",
    "ADJUSTMENT_TYPE": "HAZARD_BUMP",
    "BASE_AMOUNT": 100000,
    "REQUESTED_PCT": 0.20,
    "INCIDENT_SEVERITY": "MINOR",
    "INCIDENT_DESCRIPTION": "On-set incident",
}


def create_production_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PRODUCTION_NAME"],
        "total_budget_cents": DEFAULTS["PRODUCTION_BUDGET"],
    }
    defaults.update(overrides)
    return defaults


def file_insurance_payload(**overrides) -> dict:
    defaults = {"declared_exposure_cents": DEFAULTS["DECLARED_EXPOSURE"]}
    defaults.update(overrides)
    return defaults


def amend_budget_payload(total_budget_cents, expected_production_version) -> dict:
    return {
        "total_budget_cents": total_budget_cents,
        "expected_production_version": expected_production_version,
    }


def create_sequence_payload(production_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "name": DEFAULTS["SEQUENCE_NAME"],
        "hazard_class": DEFAULTS["HAZARD_CLASS"],
        "risk_category": DEFAULTS["RISK_CATEGORY"],
        "scheduled_execution_start": DEFAULT_EXEC_START,
        "scheduled_execution_end": DEFAULT_EXEC_END,
        "required_equipment_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_risk_assessment_payload(production_id, sequence_id, expected_sequence_version, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "sequence_id": sequence_id,
        "severity_rating": 2,
        "likelihood_rating": 2,
        "expected_sequence_version": expected_sequence_version,
    }
    defaults.update(overrides)
    return defaults


def revise_assessment_payload(**overrides) -> dict:
    defaults = {
        "severity_rating": 3,
        "likelihood_rating": 3,
        "mitigation_notes": "Added wire decelerators",
    }
    defaults.update(overrides)
    return defaults


def create_performer_payload(production_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "first_name": DEFAULTS["PERFORMER_FIRST"],
        "last_name": DEFAULTS["PERFORMER_LAST"],
        "base_day_rate_cents": DEFAULTS["DAY_RATE"],
        "union_status": DEFAULTS["UNION_STATUS"],
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(performer_id, **overrides) -> dict:
    defaults = {
        "performer_id": performer_id,
        "discipline": DEFAULTS["DISCIPLINE"],
        "level": DEFAULTS["CERT_LEVEL"],
        "issued_at": DEFAULT_ISSUED_AT,
        "expires_at": DEFAULT_CERT_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_rehearsal_payload(production_id, sequence_id, performer_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "sequence_id": sequence_id,
        "performer_id": performer_id,
        "facility": DEFAULTS["FACILITY"],
        "scheduled_start": f"{REHEARSAL_DAY}T10:00:00Z",
        "scheduled_end": f"{REHEARSAL_DAY}T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_safety_meeting_payload(production_id, sequence_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "sequence_id": sequence_id,
        "facility": DEFAULTS["MEETING_FACILITY"],
        "scheduled_start": f"{MEETING_DAY}T10:00:00Z",
        "scheduled_end": f"{MEETING_DAY}T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(production_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "name": DEFAULTS["EQUIPMENT_NAME"],
        "equipment_type": DEFAULTS["EQUIPMENT_TYPE"],
        "serial_number": DEFAULTS["SERIAL"],
        "inspection_interval_hours": DEFAULTS["INSPECTION_INTERVAL_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(equipment_id, **overrides) -> dict:
    defaults = {
        "equipment_id": equipment_id,
        "outcome": "PASSED",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(production_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "permit_type": DEFAULTS["PERMIT_TYPE"],
        "jurisdiction": DEFAULTS["JURISDICTION"],
        "valid_from": "2026-07-01T00:00:00Z",
        "valid_until": "2026-08-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_pay_adjustment_payload(production_id, sequence_id, performer_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "sequence_id": sequence_id,
        "performer_id": performer_id,
        "adjustment_type": DEFAULTS["ADJUSTMENT_TYPE"],
        "base_amount_cents": DEFAULTS["BASE_AMOUNT"],
        "requested_pct": DEFAULTS["REQUESTED_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(production_id, **overrides) -> dict:
    defaults = {
        "production_id": production_id,
        "severity": DEFAULTS["INCIDENT_SEVERITY"],
        "occurred_at": f"{REHEARSAL_DAY}T12:00:00Z",
        "description": DEFAULTS["INCIDENT_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_execution_payload(production_id, sequence_id, take_number, expected_sequence_version) -> dict:
    return {
        "production_id": production_id,
        "sequence_id": sequence_id,
        "take_number": take_number,
        "expected_sequence_version": expected_sequence_version,
    }


def abort_execution_payload(**overrides) -> dict:
    defaults = {
        "abort_reason": "camera not rolling",
        "safety_related": False,
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(production_id, sequence_id) -> dict:
    return {"production_id": production_id, "sequence_id": sequence_id}


def close_review_payload(**overrides) -> dict:
    defaults = {
        "outcome": "ACCEPTED_AS_SHOT",
        "findings": "No issues found",
    }
    defaults.update(overrides)
    return defaults
