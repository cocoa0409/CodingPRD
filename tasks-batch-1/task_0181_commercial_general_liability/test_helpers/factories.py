"""Payload factories — one per entity, input fields only (CGL PRD)."""

DEFAULTS = {
    "INSURER_NAME": "Acme Mutual",
    "NAIC_CODE": "12345",
    "INSURED_NAME": "BuildCo LLC",
    "FEIN": "11-1111111",
    "HOLDER_NAME": "Landlord LLC",
    "HOLDER_ADDRESS": "1 Main St",
    "EACH_OCCURRENCE_LIMIT_CENTS": 100000000,
    "GENERAL_AGGREGATE_LIMIT_CENTS": 200000000,
    "PRODUCTS_AGGREGATE_LIMIT_CENTS": 100000000,
    "RATE_PER_UNIT_CENTS": 300,
    "MINIMUM_PREMIUM_CENTS": 100000,
    "ESTIMATED_EXPOSURE_UNITS": 1000000,
    "EFFECTIVE_DATE": "2026-01-01T00:00:00.000Z",
    "EXPIRATION_DATE": "2027-01-01T00:00:00.000Z",
}


def create_insurer_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["INSURER_NAME"],
        "naic_code": DEFAULTS["NAIC_CODE"],
    }
    payload.update(overrides)
    return payload


def create_insured_payload(insurer_id, **overrides) -> dict:
    payload = {
        "insurer_id": insurer_id,
        "legal_name": DEFAULTS["INSURED_NAME"],
        "fein": DEFAULTS["FEIN"],
        "primary_basis": "PAYROLL",
    }
    payload.update(overrides)
    return payload


def create_certificate_holder_payload(insurer_id, **overrides) -> dict:
    payload = {
        "insurer_id": insurer_id,
        "holder_name": DEFAULTS["HOLDER_NAME"],
        "address": DEFAULTS["HOLDER_ADDRESS"],
    }
    payload.update(overrides)
    return payload


def create_policy_payload(insurer_id, insured_id, policy_number="CGL-0001", **overrides) -> dict:
    payload = {
        "insurer_id": insurer_id,
        "insured_id": insured_id,
        "policy_number": policy_number,
        "coverage_trigger": "OCCURRENCE",
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "expiration_date": DEFAULTS["EXPIRATION_DATE"],
        "each_occurrence_limit_cents": DEFAULTS["EACH_OCCURRENCE_LIMIT_CENTS"],
        "general_aggregate_limit_cents": DEFAULTS["GENERAL_AGGREGATE_LIMIT_CENTS"],
        "products_aggregate_limit_cents": DEFAULTS["PRODUCTS_AGGREGATE_LIMIT_CENTS"],
        "premium_basis": "PAYROLL",
        "rate_per_unit_cents": DEFAULTS["RATE_PER_UNIT_CENTS"],
        "minimum_premium_cents": DEFAULTS["MINIMUM_PREMIUM_CENTS"],
        "estimated_exposure_units": DEFAULTS["ESTIMATED_EXPOSURE_UNITS"],
    }
    payload.update(overrides)
    return payload


def create_endorsement_payload(policy_id, certificate_holder_id, **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "certificate_holder_id": certificate_holder_id,
        "form_number": "CG2010",
        "ai_effective_date": "2026-02-01T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_certificate_payload(policy_id, certificate_holder_id, **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "certificate_holder_id": certificate_holder_id,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(policy_id, **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "claimant_name": "Claimant",
        "loss_type": "BODILY_INJURY",
        "occurrence_date": "2026-03-01T00:00:00.000Z",
        "reported_date": "2026-03-02T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_transaction_payload(txn_type, amount_cents, **overrides) -> dict:
    payload = {
        "txn_type": txn_type,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_audit_payload(policy_id, audit_basis="PAYROLL", **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "audit_basis": audit_basis,
    }
    payload.update(overrides)
    return payload


def create_exposure_record_payload(class_code="91560", basis_amount_units=1000000, **overrides) -> dict:
    payload = {
        "class_code": class_code,
        "basis_amount_units": basis_amount_units,
    }
    payload.update(overrides)
    return payload
