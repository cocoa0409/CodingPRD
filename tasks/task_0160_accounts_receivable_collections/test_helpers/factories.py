"""Payload factories — one per entity, input fields only.

Field names mirror the PRD exactly. Computed fields (balance_cents, status,
exposure_cents, etc.) are never sent.
"""

DEFAULTS = {
    "CUSTOMER_NAME": "Test Customer",
    "CREDIT_LIMIT_CENTS": 1_000_000,
    "CURRENCY": "USD",
    "INVOICE_DATE": "2026-01-01T00:00:00Z",
    "DUE_DATE": "2026-02-01T00:00:00Z",
    "FACE_AMOUNT_CENTS": 50_000,
    "PAYMENT_AMOUNT_CENTS": 50_000,
    "RECEIVED_AT": "2026-03-01T00:00:00Z",
    "DISPUTE_AMOUNT_CENTS": 10_000,
    "DISPUTE_REASON": "PRICING",
    "PROMISED_AMOUNT_CENTS": 50_000,
    "COVERAGE_START": "2026-06-01T00:00:00Z",
    "COVERAGE_END": "2026-06-30T00:00:00Z",
    "WRITEOFF_REASON": "UNCOLLECTIBLE",
    "SEQUENCE_NAME": "Default Sequence",
    "PAUSE_START": "2026-07-01T00:00:00Z",
    "PAUSE_END": "2026-07-10T00:00:00Z",
    "PERIOD_END": "2026-05-01T00:00:00Z",
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "currency": DEFAULTS["CURRENCY"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "invoice_date": DEFAULTS["INVOICE_DATE"],
        "due_date": DEFAULTS["DUE_DATE"],
        "face_amount_cents": DEFAULTS["FACE_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "amount_cents": DEFAULTS["PAYMENT_AMOUNT_CENTS"],
        "received_at": DEFAULTS["RECEIVED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_application_payload(invoice_id, applied_cents, **overrides) -> dict:
    defaults = {
        "invoice_id": invoice_id,
        "applied_cents": applied_cents,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(invoice_id, **overrides) -> dict:
    defaults = {
        "invoice_id": invoice_id,
        "amount_cents": DEFAULTS["DISPUTE_AMOUNT_CENTS"],
        "reason_code": DEFAULTS["DISPUTE_REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_promise_payload(customer_id, expected_customer_version, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "promised_amount_cents": DEFAULTS["PROMISED_AMOUNT_CENTS"],
        "coverage_start": DEFAULTS["COVERAGE_START"],
        "coverage_end": DEFAULTS["COVERAGE_END"],
        "expected_customer_version": expected_customer_version,
    }
    defaults.update(overrides)
    return defaults


def create_write_off_payload(invoice_id, amount_cents, **overrides) -> dict:
    defaults = {
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "reason_code": DEFAULTS["WRITEOFF_REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_dunning_sequence_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SEQUENCE_NAME"],
        "steps": [{"min_days_overdue": 1, "channel": "EMAIL", "severity": 1}],
    }
    defaults.update(overrides)
    return defaults


def create_dunning_run_payload(customer_id, sequence_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "sequence_id": sequence_id}
    defaults.update(overrides)
    return defaults


def create_dunning_pause_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "pause_start": DEFAULTS["PAUSE_START"],
        "pause_end": DEFAULTS["PAUSE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(**overrides) -> dict:
    defaults = {"period_end": DEFAULTS["PERIOD_END"]}
    defaults.update(overrides)
    return defaults
