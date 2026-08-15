"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import uuid

from .constants import (
    DEFAULT_DRUG,
    DEFAULT_SESSION_END,
    DEFAULT_SESSION_START,
    HEALTHY_PATIENT,
)


def _uniq(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:8]}"


def create_staff_payload(**overrides) -> dict:
    defaults = {"full_name": _uniq("Staff"), "staff_role": "PHARMACIST"}
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = dict(HEALTHY_PATIENT)
    defaults["full_name"] = _uniq("Patient")
    defaults.update(overrides)
    return defaults


def create_drug_product_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_DRUG)
    defaults["name"] = _uniq("Drug")
    defaults.update(overrides)
    return defaults


def create_hood_payload(**overrides) -> dict:
    defaults = {"name": _uniq("HOOD"), "iso_class": "ISO_5"}
    defaults.update(overrides)
    return defaults


def create_hood_session_payload(hood_id, **overrides) -> dict:
    defaults = {
        "hood_id": hood_id,
        "start_at": DEFAULT_SESSION_START,
        "end_at": DEFAULT_SESSION_END,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_shift_payload(staff_id, **overrides) -> dict:
    defaults = {
        "staff_id": staff_id,
        "zone": "CENTRAL",
        "start_at": "2026-08-01T08:00:00Z",
        "end_at": "2026-08-01T16:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(patient_id, drug_product_id, expected_patient_version,
                         **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "drug_product_id": drug_product_id,
        "route": "IV",
        "ordered_dose_mg": 100.0,
        "frequency_per_day": 1,
        "expected_patient_version": expected_patient_version,
    }
    defaults.update(overrides)
    return defaults


def create_intervention_payload(**overrides) -> dict:
    defaults = {"intervention_type": "OTHER", "note": "note"}
    defaults.update(overrides)
    return defaults


def create_batch_payload(hood_session_id, order_ids, **overrides) -> dict:
    defaults = {
        "hood_session_id": hood_session_id,
        "order_ids": list(order_ids),
        "usp_risk_level": "LOW",
    }
    defaults.update(overrides)
    return defaults


def complete_batch_payload(prepared_volumes_ml, **overrides) -> dict:
    defaults = {
        "prepared_volumes_ml": list(prepared_volumes_ml),
        "waste_ml": 0.0,
        "storage_condition": "ROOM",
    }
    defaults.update(overrides)
    return defaults


def create_adc_station_payload(**overrides) -> dict:
    defaults = {"name": _uniq("ST"), "zone": "CENTRAL"}
    defaults.update(overrides)
    return defaults


def create_adc_pocket_payload(drug_product_id, **overrides) -> dict:
    defaults = {"drug_product_id": drug_product_id, "max_units": 100}
    defaults.update(overrides)
    return defaults


def restock_payload(units, expected_pocket_version) -> dict:
    return {"units": units, "expected_pocket_version": expected_pocket_version}


def dispense_payload(order_id, units) -> dict:
    return {"order_id": order_id, "units": units}


def return_payload(units, **overrides) -> dict:
    defaults = {"units": units}
    defaults.update(overrides)
    return defaults


def waste_payload(units, **overrides) -> dict:
    defaults = {"units": units}
    defaults.update(overrides)
    return defaults


def count_payload(physical_count_units) -> dict:
    return {"physical_count_units": physical_count_units}


def resolve_discrepancy_payload(resolution, **overrides) -> dict:
    defaults = {"resolution": resolution}
    defaults.update(overrides)
    return defaults


def create_diversion_case_payload(station_id, subject_staff_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "subject_staff_id": subject_staff_id,
        "reason": "manual review",
    }
    defaults.update(overrides)
    return defaults


def adjudicate_payload(outcome, note) -> dict:
    return {"outcome": outcome, "note": note}


def evaluate_risk_payload(station_id, subject_staff_id, drug_product_id) -> dict:
    return {
        "station_id": station_id,
        "subject_staff_id": subject_staff_id,
        "drug_product_id": drug_product_id,
    }


def create_substitution_protocol_payload(shortage_drug_product_id,
                                         substitute_drug_product_id,
                                         **overrides) -> dict:
    defaults = {
        "shortage_drug_product_id": shortage_drug_product_id,
        "substitute_drug_product_id": substitute_drug_product_id,
        "conversion_factor": 0.5,
        "max_dose_mg": 200.0,
        "expires_at": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
