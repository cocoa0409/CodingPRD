"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def create_student_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "student_number": f"S{n:07d}"[-9:],
        "full_name": f"Test Student {n}",
        "date_of_birth": "2000-01-01",
        "email": f"student{n}@example.edu",
    }
    defaults.update(overrides)
    return defaults


def publish_record_payload(**overrides) -> dict:
    defaults = {
        "effective_term": "2026-SPR",
        "earned_credits": 3,
        "courses": [{"grade_points": 4.0, "credits": 3}],
    }
    defaults.update(overrides)
    return defaults


def create_recipient_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "kind": "EMAIL_PDF",
        "display_name": f"Recipient {n}",
        "email_address": f"recipient{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_hold_payload(**overrides) -> dict:
    defaults = {
        "hold_type": "FINANCIAL",
        "blocking_scope": "OFFICIAL",
        "amount_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_identity_verification_payload(**overrides) -> dict:
    defaults = {
        "method": "SSN_DOB",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "order_kind": "OFFICIAL",
        "rush_requested": False,
    }
    defaults.update(overrides)
    return defaults


def add_line_item_payload(**overrides) -> dict:
    defaults = {
        "delivery_kind": "EMAIL_PDF",
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "idempotency_key": f"pay-key-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_consent_grant_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "grantee_name": f"Employer {n}",
        "scope": "DEGREE_ONLY",
        "expires_at": "2027-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_verification_request_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "requester_name": f"Employer {n}",
        "scope": "ENROLLMENT_ONLY",
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "code": f"FS-{n:05d}",
        "official_base_cents": TEST_DEFAULTS["OFFICIAL_BASE_CENTS"],
        "unofficial_base_cents": TEST_DEFAULTS["UNOFFICIAL_BASE_CENTS"],
        "paper_surcharge_cents": TEST_DEFAULTS["PAPER_SURCHARGE_CENTS"],
        "pickup_surcharge_cents": TEST_DEFAULTS["PICKUP_SURCHARGE_CENTS"],
        "rush_flat_cents": TEST_DEFAULTS["RUSH_FLAT_CENTS"],
        "rush_multiplier_bp": TEST_DEFAULTS["RUSH_MULTIPLIER_BP"],
        "volume_tiers": [],
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_clearinghouse_batch_payload(**overrides) -> dict:
    defaults = {
        "report_period_start": "2026-08-01T00:00:00Z",
        "report_period_end": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_archived_retrieval_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_reissue_request_payload(**overrides) -> dict:
    defaults = {
        "reason": "NAME_CORRECTION",
    }
    defaults.update(overrides)
    return defaults
