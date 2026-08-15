"""Payload factories — one per entity, input fields only (PRD §3/§4).

Unique-ish identifier fields (dot_number, cdl_number, report_number) are
auto-generated from a process-wide counter so multi-entity tests never
collide; callers override them freely.
"""
import itertools

_counter = itertools.count(1)


def _next(prefix: str) -> str:
    return f"{prefix}-{next(_counter):05d}"


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "dot_number": _next("DOT"),
        "legal_name": "Test Carrier LLC",
        "fleet_size": 2,
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(carrier_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "cdl_number": _next("CDL"),
        "full_name": "Test Driver",
        "hire_date": "2025-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_category_payload(**overrides) -> dict:
    defaults = {
        "category_code": "VEHICLE_MAINTENANCE",
        "display_name": "Vehicle Maintenance",
        "intervention_threshold": 65,
        "benchmark_measure": 10.0,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(carrier_id, driver_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "driver_id": driver_id,
        "report_number": _next("R"),
        "inspection_date": "2026-05-01T00:00:00Z",
        "inspection_level": 1,
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(inspection_id, category_id, **overrides) -> dict:
    defaults = {
        "inspection_id": inspection_id,
        "category_id": category_id,
        "violation_code": "396.3",
        "severity_weight": 5,
        "occurred_at": "2026-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_challenge_payload(violation_id, **overrides) -> dict:
    defaults = {
        "violation_id": violation_id,
        "reason_code": "OTHER",
        "evidence_note": "Supporting evidence attached",
    }
    defaults.update(overrides)
    return defaults


def create_coaching_payload(driver_id, expected_driver_version, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "coaching_type": "TRAINING_COURSE",
        "due_date": "2027-01-01T00:00:00Z",
        "expected_driver_version": expected_driver_version,
    }
    defaults.update(overrides)
    return defaults


def create_test_payload(driver_id, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "test_type": "RANDOM",
        "substance": "DRUG",
        "collected_at": "2026-07-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_accident_payload(carrier_id, driver_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "driver_id": driver_id,
        "occurred_at": "2026-06-01T00:00:00Z",
        "fatalities": 0,
        "injuries": 1,
        "tow_away": False,
    }
    defaults.update(overrides)
    return defaults


def create_audit_case_payload(carrier_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "audit_type": "COMPLIANCE_REVIEW",
        "scheduled_date": "2026-08-01T00:00:00Z",
        "field_work_duration_days": 7,
    }
    defaults.update(overrides)
    return defaults


def create_upgrade_request_payload(carrier_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "requested_rating": "SATISFACTORY",
        "justification_note": "Corrective-action evidence",
    }
    defaults.update(overrides)
    return defaults


def create_premium_model_payload(carrier_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "policy_period_start": "2027-01-01T00:00:00Z",
        "policy_period_end": "2027-12-31T00:00:00Z",
        "base_rate_cents_per_unit": 100000,
        "scenario": "BASELINE",
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(carrier_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "document_type": "INSPECTION_REPORT",
        "filed_at": "2026-01-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_period_payload(carrier_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "program_year": 2026,
        "avg_driver_count": 8,
    }
    defaults.update(overrides)
    return defaults
