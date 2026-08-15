"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "MRN": "MRN-1000",
    "FULL_NAME": "Test Patient",
    "DATE_OF_BIRTH": "1980-01-01",
    "CPT_CODE": "27447",
    "DESCRIPTION": "Total knee arthroplasty",
    "LIST_PRICE_CENTS": 5000000,
    "PAYER_CODE": "ACME",
    "PAYER_NAME": "Acme Health",
    "RATE_CENTS": 3000000,
    "EFFECTIVE_FROM": "2026-01-01",
    "MEMBER_ID": "M-1000",
    "SERVICE_DATE": "2026-08-20",
    "SERVICE_DESCRIPTION": "Scheduled knee replacement",
    "DEDUCTIBLE_TOTAL_CENTS": 150000,
    "DEDUCTIBLE_MET_CENTS": 50000,
    "OOP_MAX_CENTS": 600000,
    "OOP_MET_CENTS": 100000,
    "COINSURANCE_PCT": 20,
}


def create_charge_item_payload(**overrides) -> dict:
    defaults = {
        "cpt_code": DEFAULTS["CPT_CODE"],
        "description": DEFAULTS["DESCRIPTION"],
        "list_price_cents": DEFAULTS["LIST_PRICE_CENTS"],
        "requires_auth_prior": False,
    }
    defaults.update(overrides)
    return defaults


def create_payer_contract_payload(**overrides) -> dict:
    defaults = {
        "payer_code": DEFAULTS["PAYER_CODE"],
        "payer_name": DEFAULTS["PAYER_NAME"],
        "bundling_rule": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_contract_rate_payload(**overrides) -> dict:
    defaults = {
        "cpt_code": DEFAULTS["CPT_CODE"],
        "rate_cents": DEFAULTS["RATE_CENTS"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "mrn": DEFAULTS["MRN"],
        "full_name": DEFAULTS["FULL_NAME"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
    }
    defaults.update(overrides)
    return defaults


def create_eligibility_snapshot_payload(expected_patient_version, **overrides) -> dict:
    defaults = {
        "expected_patient_version": expected_patient_version,
        "payer_code": DEFAULTS["PAYER_CODE"],
        "member_id": DEFAULTS["MEMBER_ID"],
        "deductible_total_cents": DEFAULTS["DEDUCTIBLE_TOTAL_CENTS"],
        "deductible_met_cents": DEFAULTS["DEDUCTIBLE_MET_CENTS"],
        "oop_max_cents": DEFAULTS["OOP_MAX_CENTS"],
        "oop_met_cents": DEFAULTS["OOP_MET_CENTS"],
        "coinsurance_pct": DEFAULTS["COINSURANCE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "service_date": DEFAULTS["SERVICE_DATE"],
        "service_description": DEFAULTS["SERVICE_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(expected_case_version, pricing_mode, lines,
                            eligibility_snapshot_id=None, **overrides) -> dict:
    payload = {
        "expected_case_version": expected_case_version,
        "pricing_mode": pricing_mode,
        "lines": lines,
    }
    if eligibility_snapshot_id is not None:
        payload["eligibility_snapshot_id"] = eligibility_snapshot_id
    payload.update(overrides)
    return payload


def create_authorization_payload(**overrides) -> dict:
    defaults = {
        "cpt_codes": [DEFAULTS["CPT_CODE"]],
        "payer_code": DEFAULTS["PAYER_CODE"],
    }
    defaults.update(overrides)
    return defaults


def decide_authorization_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_payment_plan_payload(**overrides) -> dict:
    defaults = {
        "principal_cents": 100001,
        "num_installments": 3,
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 100000,
        "method": "CARD",
    }
    defaults.update(overrides)
    return defaults


def create_escalation_payload(**overrides) -> dict:
    defaults = {
        "reason": "AUTH_EXCEPTION",
    }
    defaults.update(overrides)
    return defaults
