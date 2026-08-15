"""Payload factories — one per creatable resource, input fields only."""

from .constants import TEST_DEFAULTS


def create_bank_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["BANK_LEGAL_NAME"],
        "routing_number": TEST_DEFAULTS["BANK_ROUTING_NUMBER"],
        "default_earnings_credit_rate_bp": TEST_DEFAULTS["BANK_ECR_BP"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["CUSTOMER_LEGAL_NAME"],
        "tax_id": TEST_DEFAULTS["CUSTOMER_TAX_ID"],
        "deposit_account_number": TEST_DEFAULTS["CUSTOMER_DDA"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "agreement_number": TEST_DEFAULTS["AGREEMENT_NUMBER"],
        "monthly_maintenance_fee_cents": 0,
        "per_item_capture_fee_cents": 0,
        "per_exception_decision_fee_cents": 0,
        "per_image_retrieval_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(**overrides) -> dict:
    defaults = {
        "site_code": TEST_DEFAULTS["SITE_CODE"],
        "postal_box_address": TEST_DEFAULTS["SITE_POSTAL_BOX"],
        "daily_cutoff_time_local": TEST_DEFAULTS["SITE_CUTOFF"],
        "timezone": TEST_DEFAULTS["SITE_TIMEZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_availability_schedule_payload(**overrides) -> dict:
    defaults = {
        "routing_number_pattern": TEST_DEFAULTS["SCHEDULE_PATTERN"],
        "tier": "SAME_DAY",
        "effective_from": "2026-08-01",
        "priority": 1,
    }
    defaults.update(overrides)
    return defaults


def create_transmission_format_payload(**overrides) -> dict:
    defaults = {
        "format_kind": "BAI2",
        "version_label": "v1",
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    defaults = {
        "batch_reference": "B-1",
        "received_at": TEST_DEFAULTS["RECEIVED_BEFORE_CUTOFF"],
        "declared_item_count": 1,
        "declared_total_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(**overrides) -> dict:
    defaults = {
        "check_number": "1",
        "payer_routing_number": TEST_DEFAULTS["PAYER_ROUTING"],
        "amount_cents": 1000,
        "payee_name": "Acme Corp",
    }
    defaults.update(overrides)
    return defaults


def raise_exception_payload(**overrides) -> dict:
    defaults = {
        "reason_code": "AMOUNT_MISMATCH",
        "default_decision": "PAY",
    }
    defaults.update(overrides)
    return defaults


def create_image_request_payload(item_id, **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "request_reason": "AUDIT",
        "requested_image_kinds": ["CHECK_FRONT"],
    }
    defaults.update(overrides)
    return defaults


def create_sla_incident_payload(**overrides) -> dict:
    defaults = {
        "incident_kind": "LATE_TRANSMISSION",
        "occurred_on_business_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_error_credit_request_payload(cycle_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "requested_credit_cents": 1000,
        "reason_code": "BILLING_RATE_ERROR",
    }
    defaults.update(overrides)
    return defaults
