"""Payload factories — one per entity, input fields only.

Each factory builds a valid default body for a create/transition call and accepts
**overrides for the values a test needs to control.
"""
from .constants import FAR_FUTURE_EXPIRY, DEFAULT_CLOCK


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Facility",
        "registration_type": "503A",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str = DEFAULT_CLOCK, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


def create_mfr_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "name": "Test Formula 100mg",
        "dosage_form": "ORAL_SOLID",
        "default_bud_days_nonsterile": 90,
        "theoretical_yield_units": 100,
        "anticipatory_max_units": 500,
    }
    defaults.update(overrides)
    return defaults


def create_ingredient_lot_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "component_name": "Test API",
        "lot_number": "LOT-1",
        "labeled_potency_pct": 100,
        "initial_grams": 50,
        "expiration_utc": FAR_FUTURE_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_environmental_log_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "usp_chapter": "USP_797",
        "reading_type": "VIABLE_AIR_CFU",
        "measured_value": 3,
        "action_limit": 5,
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(facility_id: str, mfr_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "master_formulation_record_id": mfr_id,
        "patient_name": "Test Patient",
        "prescriber_npi": "1234567890",
        "units_prescribed": 5,
        "written_utc": DEFAULT_CLOCK,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(facility_id: str, mfr_id: str, purpose: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "master_formulation_record_id": mfr_id,
        "purpose": purpose,
    }
    defaults.update(overrides)
    return defaults


def create_batch_ingredient_usage_payload(batch_id: str, lot_id: str, **overrides) -> dict:
    defaults = {
        "compounding_batch_id": batch_id,
        "ingredient_lot_id": lot_id,
        "grams_used": 10,
    }
    defaults.update(overrides)
    return defaults


def compile_payload(actual_yield_units: int, **overrides) -> dict:
    defaults = {"actual_yield_units": actual_yield_units}
    defaults.update(overrides)
    return defaults


def release_payload(expected_batch_version: int, **overrides) -> dict:
    defaults = {"expected_batch_version": expected_batch_version}
    defaults.update(overrides)
    return defaults


def create_qc_test_payload(batch_id: str, test_type: str, **overrides) -> dict:
    defaults = {
        "compounding_batch_id": batch_id,
        "test_type": test_type,
    }
    defaults.update(overrides)
    return defaults


def record_qc_payload(measured_value=None, pass_flag=None, **overrides) -> dict:
    """Body for POST /qc-tests/{qid}/record.

    The PRD field is literally `pass` (a Python keyword), so callers pass it as
    `pass_flag` and it is emitted under the "pass" key.
    """
    body = {}
    if measured_value is not None:
        body["measured_value"] = measured_value
    if pass_flag is not None:
        body["pass"] = pass_flag
    body.update(overrides)
    return body


def create_dispense_payload(facility_id: str, finished_preparation_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "finished_preparation_id": finished_preparation_id,
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(facility_id: str, batch_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "compounding_batch_id": batch_id,
        "reason": "POTENCY_OOS",
        "classification": "CLASS_II",
    }
    defaults.update(overrides)
    return defaults
