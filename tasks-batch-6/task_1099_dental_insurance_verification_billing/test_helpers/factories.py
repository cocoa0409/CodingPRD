"""Payload factories — one per entity, input fields only."""


def create_patient_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Patient",
        "date_of_birth": "1980-01-01",
        "email": "test@example.com",
    }
    payload.update(overrides)
    return payload


def create_insurance_plan_payload(**overrides) -> dict:
    payload = {
        "payer_name": "Delta",
        "plan_name": "P1",
        "annual_maximum_cents": 150000,
        "deductible_cents": 5000,
        "deductible_applies_to": ["BASIC", "MAJOR"],
        "preventive_coinsurance_pct": 100,
        "basic_coinsurance_pct": 80,
        "major_coinsurance_pct": 50,
        "cob_method": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_procedure_payload(**overrides) -> dict:
    payload = {
        "cdt_code": "D2740",
        "description": "Crown",
        "category": "MAJOR",
        "ucr_fee_cents": 120000,
    }
    payload.update(overrides)
    return payload


def create_coverage_payload(patient_id, insurance_plan_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "insurance_plan_id": insurance_plan_id,
        "priority": "PRIMARY",
        "subscriber_id": "S1",
        "effective_date": "2026-01-01",
        "term_date": "2026-12-31",
    }
    payload.update(overrides)
    return payload


def create_verification_payload(expected_coverage_version, **overrides) -> dict:
    payload = {
        "expected_coverage_version": expected_coverage_version,
        "verified_annual_maximum_cents": 150000,
        "verified_deductible_cents": 5000,
        "verified_preventive_pct": 100,
        "verified_basic_pct": 80,
        "verified_major_pct": 50,
    }
    payload.update(overrides)
    return payload


def create_preauthorization_payload(patient_id, coverage_id, procedures, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "coverage_id": coverage_id,
        "procedures": procedures,
    }
    payload.update(overrides)
    return payload


def create_attachment_payload(**overrides) -> dict:
    payload = {
        "kind": "XRAY",
        "filename": "attachment.png",
    }
    payload.update(overrides)
    return payload


def create_claim_payload(patient_id, coverage_id, procedures, service_date, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "coverage_id": coverage_id,
        "procedures": procedures,
        "service_date": service_date,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(patient_id, payer_type, amount_cents, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "payer_type": payer_type,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_membership_plan_payload(**overrides) -> dict:
    payload = {
        "name": "Basic",
        "annual_fee_cents": 30000,
        "billing_period": "MONTHLY",
    }
    payload.update(overrides)
    return payload


def create_membership_payload(patient_id, membership_plan_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "membership_plan_id": membership_plan_id,
        "period_start": "2026-05-01",
        "period_end": "2027-05-01",
    }
    payload.update(overrides)
    return payload
