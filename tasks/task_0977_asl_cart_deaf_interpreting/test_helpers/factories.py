"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_org_payload(**overrides) -> dict:
    defaults = {
        "name": "Metro Hospital",
        "org_type": "MEDICAL",
        "credit_limit_cents": TEST_DEFAULTS["ORG_CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_card_payload(**overrides) -> dict:
    """On-site ASL / MEDICAL / CERTIFIED card with the standard fixture rates."""
    defaults = {
        "modality": "ASL_ONSITE",
        "ada_context": "MEDICAL",
        "credential_level": "CERTIFIED",
        "hourly_rate_cents": TEST_DEFAULTS["HOURLY_RATE_CENTS"],
        "minimum_billable_minutes": TEST_DEFAULTS["MINIMUM_BILLABLE_MINUTES"],
        "travel_rate_cents_per_hour": TEST_DEFAULTS["TRAVEL_RATE_CENTS_PER_HOUR"],
        "mileage_rate_cents_per_mile": TEST_DEFAULTS["MILEAGE_RATE_CENTS_PER_MILE"],
        "vri_platform_fee_cents_per_min": TEST_DEFAULTS["VRI_PLATFORM_FEE_CENTS_PER_MIN"],
        "cancel_full_refund_notice_hours": TEST_DEFAULTS["CANCEL_FULL_REFUND_NOTICE_HOURS"],
        "cancel_partial_notice_hours": TEST_DEFAULTS["CANCEL_PARTIAL_NOTICE_HOURS"],
        "late_cancel_fee_pct": TEST_DEFAULTS["LATE_CANCEL_FEE_PCT"],
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_vri_rate_card_payload(**overrides) -> dict:
    """VRI / GENERAL / SCREENED card: zero travel/mileage, 15 cents/min platform fee."""
    defaults = {
        "modality": "VRI",
        "ada_context": "GENERAL",
        "credential_level": "SCREENED",
        "hourly_rate_cents": TEST_DEFAULTS["VRI_HOURLY_RATE_CENTS"],
        "minimum_billable_minutes": TEST_DEFAULTS["VRI_MINIMUM_BILLABLE_MINUTES"],
        "travel_rate_cents_per_hour": 0,
        "mileage_rate_cents_per_mile": 0,
        "vri_platform_fee_cents_per_min": TEST_DEFAULTS["VRI_PLATFORM_FEE_PER_MIN"],
        "cancel_full_refund_notice_hours": TEST_DEFAULTS["CANCEL_FULL_REFUND_NOTICE_HOURS"],
        "cancel_partial_notice_hours": TEST_DEFAULTS["CANCEL_PARTIAL_NOTICE_HOURS"],
        "late_cancel_fee_pct": TEST_DEFAULTS["LATE_CANCEL_FEE_PCT"],
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_interpreter_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ana ASL",
        "modalities_offered": ["ASL_ONSITE"],
        "home_zip": "02139",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults = {
        "credential": "RID_NIC",
        "level": "CERTIFIED",
        "issued_on": "2024-01-01T00:00:00Z",
        "expires_on": "2028-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_availability_window_payload(**overrides) -> dict:
    defaults = {
        "start_at": TEST_DEFAULTS["AVAILABILITY_START"],
        "end_at": TEST_DEFAULTS["AVAILABILITY_END"],
        "modalities": ["ASL_ONSITE"],
    }
    defaults.update(overrides)
    return defaults


def create_request_payload(org_id: str, **overrides) -> dict:
    defaults = {
        "org_id": org_id,
        "consumer_name": "Pat Patient",
        "modality": "ASL_ONSITE",
        "ada_context": "MEDICAL",
        "scheduled_start": TEST_DEFAULTS["REQUEST_START"],
        "scheduled_end": TEST_DEFAULTS["REQUEST_END"],
        "onsite_address": TEST_DEFAULTS["ONSITE_ADDRESS"],
        "estimated_mileage": TEST_DEFAULTS["ESTIMATED_MILEAGE"],
    }
    defaults.update(overrides)
    # None means "omit the field" (e.g. onsite_address on a VRI booking).
    return {k: v for k, v in defaults.items() if v is not None}


def create_offer_payload(interpreter_id: str, expected_request_version: int, **overrides) -> dict:
    defaults = {
        "interpreter_id": interpreter_id,
        "expected_request_version": expected_request_version,
    }
    defaults.update(overrides)
    return defaults


def create_checkout_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_complaint_payload(org_id: str, assignment_id: str, **overrides) -> dict:
    defaults = {
        "org_id": org_id,
        "assignment_id": assignment_id,
        "category": "QUALITY",
        "severity": "MINOR",
        "narrative": "Service quality issue",
    }
    defaults.update(overrides)
    return defaults


def create_credit_memo_payload(org_id: str, expected_org_version: int, **overrides) -> dict:
    defaults = {
        "org_id": org_id,
        "amount_cents": 1000,
        "expected_org_version": expected_org_version,
    }
    defaults.update(overrides)
    return defaults


def create_strike_payload(interpreter_id: str, **overrides) -> dict:
    defaults = {
        "interpreter_id": interpreter_id,
        "occurred_at": "2026-04-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "window_start": "2026-06-01T00:00:00Z",
        "window_end": "2026-07-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
