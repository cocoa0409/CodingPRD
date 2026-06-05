"""Payload factories — one per entity, input fields only.

Each factory returns a dict of source:input fields with sensible defaults; pass
**overrides to control the values a test cares about.
"""

# Monotonic NPI generator so providers created in one test never collide.
_npi_counter = [3_000_000_000]


def next_npi() -> str:
    _npi_counter[0] += 1
    return str(_npi_counter[0])


def create_patient_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Patient", "date_of_birth": "1990-01-01"}
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Provider",
        "provider_type": "DENTIST",
        "npi": next_npi(),
    }
    defaults.update(overrides)
    return defaults


def create_operatory_payload(**overrides) -> dict:
    defaults = {"room_name": "OP-1", "turnover_buffer_minutes": 15}
    defaults.update(overrides)
    return defaults


def create_insurance_plan_payload(**overrides) -> dict:
    defaults = {
        "carrier_name": "DeltaDent",
        "annual_maximum_cents": 100_000,
        "deductible_cents": 5_000,
        "preventive_coinsurance_pct": 100,
        "basic_coinsurance_pct": 80,
        "major_coinsurance_pct": 50,
        "major_waiting_period_months": 0,
        "frequency_limit_months": 0,
    }
    defaults.update(overrides)
    return defaults


def create_patient_coverage_payload(patient_id, insurance_plan_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "insurance_plan_id": insurance_plan_id,
        "coverage_start_date": "2025-01-01",
        "benefit_year_start_date": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_tooth_chart_payload(provider_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "tooth_number": 14,
        "chart_type": "SURFACE",
        "surface": "O",
        "finding": "caries",
    }
    defaults.update(overrides)
    return defaults


def create_treatment_plan_payload(patient_id, provider_id, **overrides) -> dict:
    defaults = {"patient_id": patient_id, "provider_id": provider_id}
    defaults.update(overrides)
    return defaults


def create_treatment_plan_item_payload(**overrides) -> dict:
    defaults = {
        "cdt_code": "D2740",
        "category": "BASIC",
        "fee_cents": 40_000,
        "phase_number": 1,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(patient_id, provider_id, operatory_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "operatory_id": operatory_id,
        "appointment_type": "OPERATIVE",
        "start_at": "2026-03-01T09:00:00Z",
        "end_at": "2026-03-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_predetermination_payload(treatment_plan_item_id, patient_coverage_id, **overrides) -> dict:
    defaults = {
        "treatment_plan_item_id": treatment_plan_item_id,
        "patient_coverage_id": patient_coverage_id,
    }
    defaults.update(overrides)
    return defaults


def approve_predetermination_payload(**overrides) -> dict:
    defaults = {"approved_benefit_cents": 42_500, "valid_until_date": "2027-01-01"}
    defaults.update(overrides)
    return defaults


def create_claim_payload(patient_id, treatment_plan_item_id, patient_coverage_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "treatment_plan_item_id": treatment_plan_item_id,
        "patient_coverage_id": patient_coverage_id,
    }
    defaults.update(overrides)
    return defaults


def create_claim_attachment_payload(**overrides) -> dict:
    defaults = {"attachment_type": "XRAY", "document_ref": "ref://doc1"}
    defaults.update(overrides)
    return defaults


def create_recare_recall_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "recall_type": "PROPHY",
        "interval_months": 6,
        "last_visit_date": "2026-01-15",
    }
    defaults.update(overrides)
    return defaults


def fulfill_recare_recall_payload(**overrides) -> dict:
    defaults = {"visit_date": "2026-07-15"}
    defaults.update(overrides)
    return defaults


def create_payment_plan_payload(patient_id, claim_id, expected_claim_version, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "claim_id": claim_id,
        "installment_count": 7,
        "expected_claim_version": expected_claim_version,
    }
    defaults.update(overrides)
    return defaults
