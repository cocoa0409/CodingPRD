"""Payload factories - one per entity, input fields only."""


def create_family_account_payload(**overrides) -> dict:
    defaults = {
        "family_name": "Test Family",
        "billing_email": "test@example.com",
        "guardian_user_id": "guardian-test",
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(family_account_id, **overrides) -> dict:
    defaults = {
        "family_account_id": family_account_id,
        "full_name": "Test Patient",
        "date_of_birth": "2012-01-01T00:00:00Z",
        "is_minor": True,
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "provider_user_id": "provider-test",
        "full_name": "Dr. Test",
        "npi": "1234567890",
    }
    defaults.update(overrides)
    return defaults


def create_chair_payload(**overrides) -> dict:
    defaults = {
        "label": "Chair-Test",
    }
    defaults.update(overrides)
    return defaults


def create_growth_record_payload(patient_id, record_type, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "record_type": record_type,
        "taken_at": "2026-02-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "carrier_name": "Test Carrier",
        "ortho_rider": True,
        "ortho_coverage_pct": 0.50,
        "lifetime_max_cents": 200000,
    }
    defaults.update(overrides)
    return defaults


def create_treatment_plan_payload(patient_id, modality="BRACES", **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "modality": modality,
    }
    defaults.update(overrides)
    return defaults


def create_treatment_phase_payload(plan_id, sequence_no, phase_fee_cents, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "sequence_no": sequence_no,
        "label": f"Phase {sequence_no}",
        "phase_fee_cents": phase_fee_cents,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(plan_id, expected_plan_version, term_months=3,
                            down_payment_cents=0, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "expected_plan_version": expected_plan_version,
        "down_payment_cents": down_payment_cents,
        "term_months": term_months,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(contract_id, amount_cents, method="CARD", **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "amount_cents": amount_cents,
        "method": method,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_claim_payload(policy_id, plan_id, billed_amount_cents, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "plan_id": plan_id,
        "billed_amount_cents": billed_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(patient_id, provider_id, chair_id, visit_type,
                               starts_at, ends_at, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "chair_id": chair_id,
        "visit_type": visit_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults
