"""Payload factories — one per entity, input fields only (PRD §3)."""

CLOCK_EPOCH = "2026-01-01T00:00:00.000Z"


def create_drug_product_payload(**overrides) -> dict:
    """POST /drug-products. Required: ndc, name, unit_price_cents."""
    defaults = {
        "ndc": "00000-0000-01",
        "name": "Test Drug",
        "unit_price_cents": 500,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_plan_payload(**overrides) -> dict:
    """POST /insurance-plans. Required: bin, pcn, name, copay_pct, copay_max_cents."""
    defaults = {
        "bin": "600000",
        "pcn": "TST",
        "name": "Test Plan",
        "copay_pct": 0.10,
        "copay_max_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_formulary_entry_payload(plan_id, drug_id, **overrides) -> dict:
    """POST /formulary-entries. Required: plan_id, drug_id, tier, allowed_amount_cents."""
    defaults = {
        "plan_id": plan_id,
        "drug_id": drug_id,
        "tier": 2,
        "allowed_amount_cents": 400,
    }
    defaults.update(overrides)
    return defaults


def create_interaction_rule_payload(drug_a_id, drug_b_id, **overrides) -> dict:
    """POST /interaction-rules. Required: drug_a_id, drug_b_id, severity, detail."""
    defaults = {
        "drug_a_id": drug_a_id,
        "drug_b_id": drug_b_id,
        "severity": "MODERATE",
        "detail": "Test interaction",
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    """POST /patients. Required: full_name, date_of_birth."""
    defaults = {
        "full_name": "Test Patient",
        "date_of_birth": "1980-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_prescriber_payload(**overrides) -> dict:
    """POST /prescribers. Required: full_name, npi."""
    defaults = {
        "full_name": "Test Prescriber",
        "npi": "1000000000",
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(patient_id, prescriber_id, drug_id, **overrides) -> dict:
    """POST /prescriptions. Required: patient_id, prescriber_id, drug_id,
    quantity_per_fill, days_supply, written_utc."""
    defaults = {
        "patient_id": patient_id,
        "prescriber_id": prescriber_id,
        "drug_id": drug_id,
        "quantity_per_fill": 30,
        "days_supply": 30,
        "written_utc": CLOCK_EPOCH,
    }
    defaults.update(overrides)
    return defaults


def create_fill_payload(prescription_id, **overrides) -> dict:
    """POST /fills. Required: prescription_id."""
    defaults = {"prescription_id": prescription_id}
    defaults.update(overrides)
    return defaults


def override_dur_payload(override_reason="Pharmacist override", **overrides) -> dict:
    """POST /fills/{id}/override-dur. override_reason is mandatory only when a
    SEVERE alert is present (PRD §3.4); always supplying it is safe."""
    defaults = {"override_reason": override_reason}
    defaults.update(overrides)
    return defaults


def submit_claim_payload(expected_prescription_version, **overrides) -> dict:
    """POST /fills/{id}/submit-claim. Required: expected_prescription_version."""
    defaults = {"expected_prescription_version": expected_prescription_version}
    defaults.update(overrides)
    return defaults


def approve_pa_payload(expected_priorauthrequest_version, **overrides) -> dict:
    """POST /prior-auth-requests/{id}/approve."""
    defaults = {"expected_priorauthrequest_version": expected_priorauthrequest_version}
    defaults.update(overrides)
    return defaults


def deny_pa_payload(expected_priorauthrequest_version, **overrides) -> dict:
    """POST /prior-auth-requests/{id}/deny."""
    defaults = {"expected_priorauthrequest_version": expected_priorauthrequest_version}
    defaults.update(overrides)
    return defaults


def create_payment_record_payload(fill_id, amount_cents, **overrides) -> dict:
    """POST /payment-records. Required: fill_id, amount_cents, tendered_by."""
    defaults = {
        "fill_id": fill_id,
        "amount_cents": amount_cents,
        "tendered_by": "cash-1",
    }
    defaults.update(overrides)
    return defaults


def create_pdmp_report_payload(patient_id, **overrides) -> dict:
    """POST /pdmp-reports. Required: patient_id."""
    defaults = {"patient_id": patient_id}
    defaults.update(overrides)
    return defaults


def clear_pdmp_block_payload(**overrides) -> dict:
    """POST /patients/{id}/clear-pdmp-block. Required: override_reason."""
    defaults = {"override_reason": "Pharmacist clearance"}
    defaults.update(overrides)
    return defaults
