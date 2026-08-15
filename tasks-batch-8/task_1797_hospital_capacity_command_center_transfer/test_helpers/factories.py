"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["FACILITY_NAME"],
        "region": TEST_DEFAULTS["REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_bed_payload(**overrides) -> dict:
    defaults = {
        "unit": "M-1",
        "label": "B1",
        "service": "MEDICAL",
        "max_acuity": "ACUITY_3_MEDICAL_SURGICAL",
        "isolation_capability": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_physician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr Test",
        "services": ["CARDIAC"],
    }
    defaults.update(overrides)
    return defaults


def create_admission_payload(bed_id, **overrides) -> dict:
    defaults = {
        "bed_id": bed_id,
        "patient_ref": "P-1",
        "acuity": "ACUITY_3_MEDICAL_SURGICAL",
        "isolation_need": "NONE",
        "service": "MEDICAL",
    }
    defaults.update(overrides)
    return defaults


def create_transfer_request_payload(**overrides) -> dict:
    defaults = {
        "source_facility_name": TEST_DEFAULTS["SOURCE_FACILITY_NAME"],
        "patient_ref": "PT-1",
        "acuity": "ACUITY_3_MEDICAL_SURGICAL",
        "isolation_need": "NONE",
        "service": "CARDIAC",
        "priority": "URGENT",
    }
    defaults.update(overrides)
    return defaults


def create_bed_hold_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_bed_assignment_payload(bed_hold_id, expected_transfer_request_version,
                                  **overrides) -> dict:
    defaults = {
        "bed_hold_id": bed_hold_id,
        "expected_transfer_request_version": expected_transfer_request_version,
    }
    defaults.update(overrides)
    return defaults


def create_diversion_payload(**overrides) -> dict:
    defaults = {
        "level": "FULL",
        "starts_at": "2026-08-01T00:00:00Z",
        "ends_at": "2026-08-01T02:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_boarding_record_payload(admission_id, **overrides) -> dict:
    defaults = {"admission_id": admission_id}
    defaults.update(overrides)
    return defaults


def create_capacity_forecast_payload(**overrides) -> dict:
    defaults = {"horizon_hours": 4}
    defaults.update(overrides)
    return defaults
