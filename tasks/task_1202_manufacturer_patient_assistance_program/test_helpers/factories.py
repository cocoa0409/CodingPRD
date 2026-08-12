"""Payload factories — one per entity, input fields only (PRD §3)."""

from .constants import (
    DEFAULT_ALLOCATED_CENTS,
    DEFAULT_LOT_EXPIRY,
    DEFAULT_PERIOD_END,
    DEFAULT_PERIOD_START,
    DEFAULT_PRIOR_YEAR_INCOME_CENTS,
)

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_program_payload(**overrides) -> dict:
    """Canonical program: cap 900000, 100 units/enrollment, 30 units/shipment,
    90-day enrollment, 90-day screening validity, 30-day appeal window,
    30-day renewal window, 30-day lot buffer, patient-direct allowed."""
    defaults = {
        "name": "PAP-LYMX",
        "product_name": "Lymxtra 100mg",
        "unit_cost_per_unit": "100.0000",
        "max_units_per_enrollment": 100,
        "max_units_per_shipment": 30,
        "max_annual_benefit_cents": 900000,
        "enrollment_duration_days": 90,
        "screening_validity_days": 90,
        "appeal_window_days": 30,
        "renewal_window_days": 30,
        "lot_expiry_buffer_days": 30,
        "allow_patient_direct_shipment": True,
    }
    defaults.update(overrides)
    return defaults


def create_minimal_program_payload(**overrides) -> dict:
    defaults = {
        "name": f"P{_next():02d}",
        "product_name": "Drug",
        "unit_cost_per_unit": "10.0000",
        "max_units_per_enrollment": 10,
        "max_units_per_shipment": 5,
        "max_annual_benefit_cents": 100000,
        "enrollment_duration_days": 90,
        "screening_validity_days": 90,
        "appeal_window_days": 30,
        "renewal_window_days": 30,
        "lot_expiry_buffer_days": 30,
        "allow_patient_direct_shipment": True,
    }
    defaults.update(overrides)
    return defaults


def create_budget_period_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "period_start": DEFAULT_PERIOD_START,
        "period_end": DEFAULT_PERIOD_END,
        "allocated_cents": DEFAULT_ALLOCATED_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Test Patient {n}",
        "date_of_birth": "1980-01-01",
        "state_code": "OH",
    }
    defaults.update(overrides)
    return defaults


def create_prescriber_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Dr. Prescriber {n}",
        "npi_number": f"{1_000_000_000 + n}",
        "state_code": "OH",
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(patient_id, program_id, **overrides) -> dict:
    """Default: PRIOR_YEAR basis, 3000000 cents, UNINSURED, household 1
    (fpl 191.69 -> ELIGIBLE)."""
    defaults = {
        "patient_id": patient_id,
        "program_id": program_id,
        "household_size": 1,
        "income_basis": "PRIOR_YEAR",
        "prior_year_income_cents": DEFAULT_PRIOR_YEAR_INCOME_CENTS,
        "insurance_status": "UNINSURED",
    }
    defaults.update(overrides)
    # PRD §3.2: conditional income/insurance fields must appear exactly when
    # the basis/status calls for them; drop *defaulted* fields that the merged
    # basis/status does not call for (explicit caller overrides are kept).
    if defaults["income_basis"] == "YTD_ANNUALIZED":
        if "prior_year_income_cents" not in overrides:
            defaults.pop("prior_year_income_cents", None)
    else:
        for f in ("ytd_income_cents", "ytd_months_elapsed"):
            if f not in overrides:
                defaults.pop(f, None)
    if defaults["insurance_status"] != "UNDERINSURED":
        if "insurance_coverage_pct" not in overrides:
            defaults.pop("insurance_coverage_pct", None)
    return defaults


def create_document_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "doc_type": "PROOF_OF_INCOME",
        "file_reference": f"s3://docs/doc-{n}.pdf",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(patient_id, program_id, screening_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "program_id": program_id,
        "screening_id": screening_id,
    }
    defaults.update(overrides)
    return defaults


def create_copay_card_payload(patient_id, program_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "program_id": program_id,
        "coverage_start": DEFAULT_PERIOD_START,
        "coverage_end": DEFAULT_PERIOD_END,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(program_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "program_id": program_id,
        "lot_number": f"LOT-{n}",
        "quantity_received": 100,
        "unit_cost_per_unit": "100.0000",
        "expiry_date": DEFAULT_LOT_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(enrollment_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "enrollment_id": enrollment_id,
        "quantity_units": 10,
        "destination": "PATIENT",
        "idempotency_key": f"idem-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_circumstance_payload(**overrides) -> dict:
    defaults = {
        "circumstance_type": "HOUSEHOLD_CHANGE",
        "new_household_size": 3,
        "note": "moved in with family",
    }
    defaults.update(overrides)
    return defaults


def create_reconciliation_payload(program_id, budget_period_id, counts, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "budget_period_id": budget_period_id,
        "counts": counts,
    }
    payload.update(overrides)
    return payload
