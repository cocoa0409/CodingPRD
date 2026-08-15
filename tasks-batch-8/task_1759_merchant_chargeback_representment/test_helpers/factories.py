"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "LEGAL_NAME": "Test Merchant",
    "MCC": "5411",
    "NETWORK": "VISA",
    "REASON_CODE": "10.4",
    "CATEGORY": "FRAUD",
    "REQUIRED_EVIDENCE": ["RECEIPT"],
    "MERCHANT_RESPONSE_DAYS": 7,
    "REPRESENTMENT_DAYS": 30,
    "CHARGEBACK_FEE_CENTS": 2500,
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "SALE_AMOUNT_CENTS": 10000,
    "OCCURRED_AT": "2026-07-10T00:00:00Z",
    "DOCUMENT_URI": "s3://evidence/doc.pdf",
    "EVIDENCE_TYPE": "RECEIPT",
    "ALERT_TYPE": "FRAUD_ALERT",
    "PROGRAM_CODE": "VDMP_STANDARD",
    "ROOT_CAUSES": ["FRAUD_GAP"],
    "ACTIONS": ["deploy 3DS"],
}


def create_merchant_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "merchant_category_code": DEFAULTS["MCC"],
    }
    defaults.update(overrides)
    return defaults


def create_reason_code_rule_payload(**overrides) -> dict:
    defaults = {
        "network": DEFAULTS["NETWORK"],
        "reason_code": DEFAULTS["REASON_CODE"],
        "category": DEFAULTS["CATEGORY"],
        "required_evidence_types": list(DEFAULTS["REQUIRED_EVIDENCE"]),
        "merchant_response_days": DEFAULTS["MERCHANT_RESPONSE_DAYS"],
        "representment_days": DEFAULTS["REPRESENTMENT_DAYS"],
        "chargeback_fee_cents": DEFAULTS["CHARGEBACK_FEE_CENTS"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(**overrides) -> dict:
    defaults = {
        "merchant_id": None,
        "external_ref": "T-1",
        "network": DEFAULTS["NETWORK"],
        "amount_cents": DEFAULTS["SALE_AMOUNT_CENTS"],
        "occurred_at": DEFAULTS["OCCURRED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_chargeback_payload(**overrides) -> dict:
    defaults = {
        "merchant_id": None,
        "transaction_external_ref": "T-1",
        "network_case_id": "NC-1",
        "reason_code": DEFAULTS["REASON_CODE"],
        "amount_cents": DEFAULTS["SALE_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_evidence_item_payload(**overrides) -> dict:
    defaults = {
        "chargeback_id": None,
        "evidence_type": DEFAULTS["EVIDENCE_TYPE"],
        "document_uri": DEFAULTS["DOCUMENT_URI"],
    }
    defaults.update(overrides)
    return defaults


def create_representment_payload(**overrides) -> dict:
    defaults = {
        "chargeback_id": None,
        "evidence_item_ids": [],
        "expected_chargeback_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_fee_assessment_payload(**overrides) -> dict:
    defaults = {
        "merchant_id": None,
        "kind": "ARBITRATION_FEE",
        "amount_cents": 7500,
    }
    defaults.update(overrides)
    return defaults


def create_program_enrollment_payload(**overrides) -> dict:
    defaults = {
        "merchant_id": None,
        "network": DEFAULTS["NETWORK"],
        "program_code": DEFAULTS["PROGRAM_CODE"],
        "enrolled_month": "2026-05",
    }
    defaults.update(overrides)
    return defaults


def create_remediation_plan_payload(**overrides) -> dict:
    defaults = {
        "enrollment_id": None,
        "root_cause_codes": list(DEFAULTS["ROOT_CAUSES"]),
        "corrective_actions": list(DEFAULTS["ACTIONS"]),
    }
    defaults.update(overrides)
    return defaults


def create_prevention_alert_payload(**overrides) -> dict:
    defaults = {
        "transaction_id": None,
        "alert_type": DEFAULTS["ALERT_TYPE"],
    }
    defaults.update(overrides)
    return defaults
