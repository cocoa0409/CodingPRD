"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_adjuster_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ada PA",
        "firm_name": "Advocate LLC",
        "email": "ada@x.com",
    }
    payload.update(overrides)
    return payload


def create_license_payload(adjuster_id, **overrides) -> dict:
    payload = {
        "adjuster_id": adjuster_id,
        "state_code": "TX",
        "license_number": "TX-1",
        "effective_date": TEST_DEFAULTS["LICENSE_EFFECTIVE_DATE"],
        "expiry_date": TEST_DEFAULTS["LICENSE_EXPIRY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_client_payload(**overrides) -> dict:
    payload = {
        "full_name": "Cy Client",
        "email": "cy@x.com",
        "mailing_state": "TX",
    }
    payload.update(overrides)
    return payload


def create_policy_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "carrier_name": "Acme",
        "policy_number": "P1",
        "policy_type": "HO3",
        "coverage_limit_cents": TEST_DEFAULTS["COVERAGE_LIMIT_CENTS"],
        "deductible_cents": TEST_DEFAULTS["DEDUCTIBLE_CENTS"],
        "effective_date": TEST_DEFAULTS["POLICY_EFFECTIVE_DATE"],
        "expiry_date": TEST_DEFAULTS["POLICY_EXPIRY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_contract_payload(client_id, adjuster_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "adjuster_id": adjuster_id,
        "loss_state_code": "TX",
        "fee_pct": TEST_DEFAULTS["FEE_PCT"],
        "statutory_cap_pct": TEST_DEFAULTS["STATUTORY_CAP_PCT"],
    }
    payload.update(overrides)
    return payload


def create_claim_payload(policy_id, contract_id, **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "contract_id": contract_id,
        "date_of_loss": TEST_DEFAULTS["DATE_OF_LOSS"],
        "loss_state_code": "TX",
        "peril_type": "WIND",
        "pa_rcv_estimate_cents": TEST_DEFAULTS["RCV_ESTIMATE_CENTS"],
        "depreciation_pct": TEST_DEFAULTS["DEPRECIATION_PCT"],
    }
    payload.update(overrides)
    return payload


def create_supplement_payload(claim_id, expected_claim_version, **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "expected_claim_version": expected_claim_version,
        "amount_cents": 1_000_000,
        "reason": "HIDDEN_DAMAGE",
    }
    payload.update(overrides)
    return payload


def create_appraisal_payload(claim_id, **overrides) -> dict:
    payload = {"claim_id": claim_id}
    payload.update(overrides)
    return payload


def name_appraisers_payload(**overrides) -> dict:
    payload = {
        "pa_appraiser_name": "Pat",
        "pa_appraiser_amount_cents": 8_000_000,
        "carrier_appraiser_name": "Casey",
        "carrier_appraiser_amount_cents": 6_000_000,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(claim_id, amount_cents, **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "amount_cents": amount_cents,
        "payment_type": "INITIAL",
    }
    payload.update(overrides)
    return payload


def create_dispute_payload(claim_id, **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "dispute_type": "FEE",
        "raised_by": "CLIENT",
        "description": "fee too high",
    }
    payload.update(overrides)
    return payload
