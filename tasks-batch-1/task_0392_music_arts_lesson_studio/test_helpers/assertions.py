"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the structural contract of a response object
against the PRD (UUID id, ISO 8601 timestamps, version integer, enum values).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_studio(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] == "OPEN", f"new studio status must be OPEN, got {data['status']}"
    assert is_iso8601_timestamp(data["current_utc"]), "current_utc must be ISO 8601"
    assert isinstance(data["makeup_credit_cap_per_enrollment"], int)
    assert isinstance(data["cancellation_notice_hours"], int)
    assert isinstance(data["makeup_credit_valid_days"], int)


def assert_family(data: dict):
    _assert_common(data)
    assert isinstance(data["household_name"], str) and len(data["household_name"]) > 0
    assert isinstance(data["autopay_enabled"], bool)
    assert isinstance(data["wallet_balance_cents"], int)
    assert data["wallet_balance_cents"] >= 0, "wallet_balance_cents is never negative"
    assert isinstance(data["active_enrollment_count"], int)
    assert data["active_enrollment_count"] >= 0
    assert isinstance(data["family_discount_pct"], (int, float))
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_student(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["skill_level"] in ("BEGINNER", "INTERMEDIATE", "ADVANCED")
    assert isinstance(data["total_practice_minutes"], int)
    assert data["total_practice_minutes"] >= 0
    assert isinstance(data["weighted_progress_score"], (int, float))
    assert data["weighted_progress_score"] >= 0


def assert_instructor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["instruments"], list)
    assert isinstance(data["weekly_availability"], list)
    assert isinstance(data["hourly_rate_cents"], int)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_room(data: dict):
    _assert_common(data)
    assert isinstance(data["room_name"], str) and len(data["room_name"]) > 0
    assert isinstance(data["supported_instruments"], list)
    assert isinstance(data["turnover_buffer_min"], int)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["lifecycle_status"] in (
        "PENDING_MATCH",
        "ACTIVE",
        "FROZEN",
        "CANCELLED",
    )
    assert data["billing_status"] in ("UNBILLED", "BILLED", "PAST_DUE")
    assert isinstance(data["monthly_tuition_cents"], int)
    assert data["instrument"] in ("PIANO", "VIOLIN", "GUITAR", "DRUMS", "VOICE", "CELLO")
    assert isinstance(data["weekday"], int)
    assert isinstance(data["start_min"], int)
    assert isinstance(data["duration_min"], int)


def assert_occurrence(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SCHEDULED",
        "COMPLETED",
        "CANCELLED_LATE",
        "CANCELLED_NOTICE",
        "MAKEUP_PENDING",
    )
    assert is_iso8601_timestamp(data["scheduled_start_utc"])
    assert is_iso8601_timestamp(data["scheduled_end_utc"])
    assert isinstance(data["is_makeup"], bool)


def assert_makeup_credit(data: dict):
    _assert_common(data)
    assert data["status"] in ("OUTSTANDING", "CONSUMED", "EXPIRED", "VOIDED")
    assert is_iso8601_timestamp(data["issued_utc"])
    assert is_iso8601_timestamp(data["expires_utc"])


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "FINALIZED", "PAID", "VOID")
    assert isinstance(data["provisional_amount_cents"], int)
    assert isinstance(data["finalized_amount_cents"], int)
    assert isinstance(data["rental_surcharge_cents"], int)
    assert isinstance(data["amount_due_cents"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUCCEEDED", "FAILED", "REFUNDED")
    assert data["method"] in ("WALLET", "AUTOPAY")
    assert data["failure_reason"] in ("NONE", "INSUFFICIENT_FUNDS")
    assert isinstance(data["amount_cents"], int)


def assert_recital_event(data: dict):
    _assert_common(data)
    assert data["status"] in ("REG_OPEN", "REG_CLOSED", "COMPLETED", "CANCELLED")
    assert isinstance(data["venue_capacity"], int)
    assert isinstance(data["confirmed_count"], int)
    assert isinstance(data["waitlist_count"], int)


def assert_registration(data: dict):
    _assert_common(data)
    assert data["status"] in ("CONFIRMED", "WAITLISTED", "WITHDRAWN")


def assert_rental(data: dict):
    _assert_common(data)
    assert data["status"] in ("RESERVED", "ACTIVE", "RETURNED", "CANCELLED")
    assert isinstance(data["period_fee_cents"], int)
