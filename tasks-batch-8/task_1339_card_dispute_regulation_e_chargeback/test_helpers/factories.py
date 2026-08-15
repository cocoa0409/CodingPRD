"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CARDHOLDER_NAME": "Test Cardholder",
    "INITIAL_BALANCE_CENTS": 100000,
    "MERCHANT_NAME": "TEST MERCHANT",
    "TXN_AMOUNT_CENTS": 10000,
    "TXN_TYPE": "ECOMMERCE",
    "NETWORK": "VISA",
    "POSTED_AT": "2026-07-01T10:00:00Z",
    "ERROR_TYPE": "INCORRECT_AMOUNT",
    "CLAIM_DELAY_DAYS": 5,
    "VERIFIED_DELAY_DAYS": 5,
    "MERCHANT_REF": "MR-1",
}


def create_card_account_payload(**overrides) -> dict:
    defaults = {
        "cardholder_name": DEFAULTS["CARDHOLDER_NAME"],
        "initial_balance_cents": DEFAULTS["INITIAL_BALANCE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_card_transaction_payload(card_account_id, **overrides) -> dict:
    defaults = {
        "card_account_id": card_account_id,
        "merchant_name": DEFAULTS["MERCHANT_NAME"],
        "amount_cents": DEFAULTS["TXN_AMOUNT_CENTS"],
        "transaction_type": DEFAULTS["TXN_TYPE"],
        "network": DEFAULTS["NETWORK"],
        "posted_at": DEFAULTS["POSTED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(card_transaction_id, claim_amount_cents, **overrides) -> dict:
    defaults = {
        "card_transaction_id": card_transaction_id,
        "error_type": DEFAULTS["ERROR_TYPE"],
        "claim_amount_cents": claim_amount_cents,
        "claimed_report_delay_days": DEFAULTS["CLAIM_DELAY_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def classify_payload(**overrides) -> dict:
    defaults = {
        "is_fraud_claim": False,
        "verified_report_delay_days": DEFAULTS["VERIFIED_DELAY_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def reclassify_payload(expected_dispute_version, **overrides) -> dict:
    defaults = {
        "is_fraud_claim": False,
        "verified_report_delay_days": DEFAULTS["VERIFIED_DELAY_DAYS"],
        "expected_dispute_version": expected_dispute_version,
    }
    defaults.update(overrides)
    return defaults


def resolve_payload(outcome="NO_ERROR", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_chargeback_payload(dispute_case_id, reason_code, **overrides) -> dict:
    defaults = {
        "dispute_case_id": dispute_case_id,
        "reason_code": reason_code,
    }
    defaults.update(overrides)
    return defaults


def create_representment_payload(**overrides) -> dict:
    defaults = {
        "merchant_ref": DEFAULTS["MERCHANT_REF"],
        "evidence_documents": [{"doc_type": "RECEIPT", "reference": "doc-1"}],
    }
    defaults.update(overrides)
    return defaults


def review_representment_payload(decision="REJECT", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def escalate_payload(stage, outcome, **overrides) -> dict:
    defaults = {"stage": stage, "outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_loss_recovery_payload(entry_type, amount_cents, **overrides) -> dict:
    defaults = {"type": entry_type, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
