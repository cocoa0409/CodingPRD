"""Payload factories — one per entity, input fields only."""


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Child",
        "date_of_birth": "2024-01-01",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Clinic",
        "vfc_pin": "PIN-TEST",
        "authorized_product_codes": [],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "product_code": "C1",
        "antigen": "C1",
        "doses_in_series": 1,
        "min_age_days": 0,
        "recommended_age_days": 0,
        "min_interval_days": 0,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    defaults = {
        "product_id": None,
        "lot_number": "L1",
        "received_date": "2024-01-01",
        "expiration_date": "2027-01-01",
        "doses_total": 50,
    }
    defaults.update(overrides)
    return defaults


def create_immunization_payload(**overrides) -> dict:
    defaults = {
        "patient_id": None,
        "lot_id": None,
        "provider_id": None,
        "administered_date": "2025-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_allergy_record_payload(**overrides) -> dict:
    defaults = {
        "patient_id": None,
        "antigen": "C1",
    }
    defaults.update(overrides)
    return defaults


def create_provider_report_payload(**overrides) -> dict:
    defaults = {
        "provider_id": None,
        "line_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_report_line_payload(**overrides) -> dict:
    defaults = {
        "patient_id": None,
        "lot_id": None,
        "administered_date": "2025-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_adverse_event_payload(**overrides) -> dict:
    defaults = {
        "immunization_id": None,
        "seriousness": "NON_SERIOUS",
        "symptoms": "test symptoms",
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(**overrides) -> dict:
    defaults = {
        "evaluation_id": None,
        "expected_patient_version": None,
    }
    defaults.update(overrides)
    return defaults
