"""Payload factories — one per entity, input fields only.

Defaults are chosen so that a factory call with no overrides produces a valid
create payload. Computed/system fields are never emitted.
"""
from .constants import TEST_DEFAULTS


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr Vega",
        "npi": TEST_DEFAULTS["NPI"],
        "license_state": TEST_DEFAULTS["LICENSE_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "name": "Adj 1",
        "room_type": "ADJUSTMENT",
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_payload(**overrides) -> dict:
    defaults = {
        "visit_type": "ADJUSTMENT",
        "cash_rate_cents": TEST_DEFAULTS["CASH_RATE_CENTS"],
        "billed_amount_cents": TEST_DEFAULTS["BILLED_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_wellness_plan_payload(**overrides) -> dict:
    defaults = {
        "name": "Gold",
        "monthly_fee_cents": 9900,
        "included_adjustments_per_month": 4,
        "overage_discount_pct": 0.30,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Patient",
        "date_of_birth": TEST_DEFAULTS["DOB"],
        "payer_mode": "CASH",
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(**overrides) -> dict:
    defaults = {
        "carrier_name": "Acme",
        "annual_visit_cap": 20,
        "deductible_total_cents": 0,
        "coinsurance_pct": 0.20,
        "allowed_amount_cents": 8000,
    }
    defaults.update(overrides)
    return defaults


def create_exam_payload(provider_id: str, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "exam_type": "INITIAL",
        "severity_score": 6,
    }
    defaults.update(overrides)
    return defaults


def create_treatment_plan_payload(exam_record_id: str, **overrides) -> dict:
    defaults = {"exam_record_id": exam_record_id}
    defaults.update(overrides)
    return defaults


def create_phase_payload(**overrides) -> dict:
    defaults = {
        "phase_type": "ACUTE",
        "sequence_index": 0,
        "visits_per_week": 3,
        "planned_visit_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_series_payload(plan_phase_id: str, provider_id: str, treatment_room_id: str, **overrides) -> dict:
    defaults = {
        "plan_phase_id": plan_phase_id,
        "provider_id": provider_id,
        "treatment_room_id": treatment_room_id,
        "start_date": "2026-03-09",
        "weekday_pattern": [0, 2, 4],
        "start_time_minutes": 540,
        "duration_minutes": TEST_DEFAULTS["DURATION_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(provider_id: str, treatment_room_id: str, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "treatment_room_id": treatment_room_id,
        "visit_type": "ADJUSTMENT",
        "scheduled_start": "2026-03-03T17:00:00Z",
        "duration_minutes": TEST_DEFAULTS["DURATION_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_soap_note_payload(provider_id: str, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "subjective": "s",
        "objective": "o",
        "assessment": "a",
        "plan": "p",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 1000}
    defaults.update(overrides)
    return defaults
