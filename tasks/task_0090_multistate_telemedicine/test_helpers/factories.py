"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Each factory provides sensible defaults and accepts
**overrides for the values a given test needs to control. Optional fields (those
the PRD marks optional or defaulted) are omitted from the defaults so tests can
exercise the server-side default behavior, and supplied only via overrides.
"""

DEFAULT_NPI = "1234567890"
DEFAULT_DEA = "BV1234567"


def create_physician_payload(**overrides) -> dict:
    """POST /physicians input: full_name, npi, dea_number?, imlc_eligible?, home_state_code."""
    defaults = {
        "full_name": "Dr Vega",
        "npi": DEFAULT_NPI,
        "home_state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_state_license_payload(**overrides) -> dict:
    """POST /physicians/{id}/state-licenses input: state_code, issuance_type,
    controlled_substance_authority?, effective_date, expiration_date."""
    defaults = {
        "state_code": "CA",
        "issuance_type": "FULL",
        "effective_date": "2026-01-01T00:00:00.000Z",
        "expiration_date": "2027-01-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    """POST /patients input: full_name, email, residence_state_code, insurance_payer_id?."""
    defaults = {
        "full_name": "Pat B",
        "email": "b@x.com",
        "residence_state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_payer_payload(**overrides) -> dict:
    """POST /payers input: name, telehealth_parity?, copay_cents, covered_state_codes,
    allowed_amount_cents."""
    defaults = {
        "name": "PlanP",
        "copay_cents": 2500,
        "covered_state_codes": ["CA"],
        "allowed_amount_cents": 8000,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(physician_id, patient_id, **overrides) -> dict:
    """POST /visits input: physician_id, patient_id, modality, scheduled_at,
    determined_state_code, list_fee_cents, platform_fee_cents?."""
    defaults = {
        "physician_id": physician_id,
        "patient_id": patient_id,
        "modality": "VIDEO",
        "scheduled_at": "2026-04-02T10:00:00.000Z",
        "determined_state_code": "CA",
        "list_fee_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(**overrides) -> dict:
    """POST /visits/{id}/prescriptions input: drug_name, dea_schedule, days_supply,
    expected_visit_prescription_version?."""
    defaults = {
        "drug_name": "Amoxicillin",
        "dea_schedule": "NONE",
        "days_supply": 10,
    }
    defaults.update(overrides)
    return defaults
