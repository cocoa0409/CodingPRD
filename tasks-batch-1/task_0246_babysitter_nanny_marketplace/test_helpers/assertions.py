"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response shape against the PRD contract.
Invariant checkers verify ledger conservation rules that must hold after any
operation.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_TIERS = ["NONE", "BASIC", "STANDARD", "PREMIUM"]


def assert_family(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["num_children"], int)
    assert 1 <= data["num_children"] <= 8
    assert data["required_tier"] in _TIERS[1:]  # BASIC|STANDARD|PREMIUM
    assert isinstance(data["wallet_balance_cents"], int) and data["wallet_balance_cents"] >= 0
    assert isinstance(data["escrow_reserved_cents"], int)
    assert isinstance(data["escrow_available_cents"], int)
    assert isinstance(data["tax_withheld_ytd_cents"], int)
    assert isinstance(data["cash_wages_ytd_cents"], int)
    assert isinstance(data["is_w2_obligated"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["version"], int)
    assert_family_escrow_invariant(data)


def assert_family_escrow_invariant(data: dict):
    """PRD 2.6: escrow_reserved + escrow_available == wallet_balance; neither
    component may go negative."""
    assert data["escrow_reserved_cents"] >= 0, "escrow_reserved_cents must never be negative"
    assert data["escrow_available_cents"] >= 0, "escrow_available_cents must never be negative"
    assert (
        data["escrow_reserved_cents"] + data["escrow_available_cents"]
        == data["wallet_balance_cents"]
    ), "escrow_reserved + escrow_available must equal wallet_balance"


def assert_caregiver(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["hourly_rate_floor_cents"], int) and data["hourly_rate_floor_cents"] >= 1
    assert data["background_check_tier"] in _TIERS
    assert data["verification_status"] in ["NONE", "PENDING", "CLEAR", "CONSIDER", "FLAGGED"]
    assert data["availability_status"] in ["AVAILABLE", "BUSY", "OFFLINE", "SUSPENDED"]
    assert isinstance(data["pending_earnings_cents"], int)
    assert isinstance(data["lifetime_paid_cents"], int)
    assert isinstance(data["rating_avg"], (int, float)) and data["rating_avg"] >= 0
    assert isinstance(data["rating_count"], int) and data["rating_count"] >= 0
    assert isinstance(data["version"], int)


def assert_background_check(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("caregiver_id", "")), "caregiver_id must be a valid UUID"
    assert data["requested_tier"] in _TIERS[1:]
    assert data["status"] in ["INITIATED", "IN_PROGRESS", "CLEAR", "CONSIDER", "FLAGGED", "EXPIRED"]
    assert isinstance(data["version"], int)


def assert_job_posting(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("family_id", "")), "family_id must be a valid UUID"
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["care_type"] in ["ONE_TIME", "RECURRING"]
    assert isinstance(data["family_pay_rate_cents"], int) and data["family_pay_rate_cents"] >= 1
    assert data["required_tier"] in _TIERS[1:]
    assert data["status"] in ["OPEN", "FILLED", "CLOSED"]
    assert isinstance(data["version"], int)


def assert_interview(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ["PHONE", "VIDEO", "TRIAL"]
    assert data["status"] in ["SCHEDULED", "PASSED", "FAILED", "TRIAL_BOOKED", "CANCELLED"]
    assert isinstance(data["version"], int)


def assert_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("family_id", "")), "family_id must be a valid UUID"
    assert is_valid_uuid(data.get("caregiver_id", "")), "caregiver_id must be a valid UUID"
    assert is_valid_uuid(data.get("job_posting_id", "")), "job_posting_id must be a valid UUID"
    assert data["care_type"] in ["ONE_TIME", "RECURRING"]
    assert isinstance(data["agreed_rate_cents"], int) and data["agreed_rate_cents"] >= 1
    assert isinstance(data["recurrence_count"], int) and data["recurrence_count"] >= 1
    assert isinstance(data["is_holiday"], bool)
    assert data["status"] in [
        "OFFERED", "COUNTERED", "CONFIRMED", "IN_PROGRESS",
        "COMPLETED", "DECLINED", "CANCELLED",
    ]
    assert isinstance(data["offer_round"], int) and data["offer_round"] >= 1
    assert isinstance(data["is_last_minute"], bool)
    assert isinstance(data["estimated_pay_cents"], int)
    assert isinstance(data["version"], int)


def assert_booking_session(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a valid UUID"
    assert is_valid_uuid(data.get("caregiver_id", "")), "caregiver_id must be a valid UUID"
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 0
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "NO_SHOW", "CANCELLED"]
    assert isinstance(data["actual_hours"], (int, float))
    assert isinstance(data["gross_pay_cents"], int)
    assert isinstance(data["is_holiday"], bool)
    assert isinstance(data["version"], int)


def assert_backup_care_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("family_id", "")), "family_id must be a valid UUID"
    assert data["required_tier"] in _TIERS[1:]
    assert isinstance(data["max_rate_cents"], int) and data["max_rate_cents"] >= 1
    assert data["status"] in ["OPEN", "MATCHED", "FULFILLED", "EXPIRED", "CANCELLED"]
    assert isinstance(data["version"], int)


def assert_payout(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("caregiver_id", "")), "caregiver_id must be a valid UUID"
    assert is_valid_uuid(data.get("family_id", "")), "family_id must be a valid UUID"
    assert isinstance(data["session_ids"], list) and len(data["session_ids"]) >= 1
    assert isinstance(data["gross_pay_cents"], int)
    assert isinstance(data["fica_withheld_cents"], int)
    assert isinstance(data["platform_fee_cents"], int)
    assert isinstance(data["net_pay_cents"], int)
    assert data["status"] in ["PENDING", "PAID", "REVERSED"]
    assert isinstance(data["version"], int)


def assert_review(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a valid UUID"
    assert isinstance(data["rating_value"], int) and 1 <= data["rating_value"] <= 5
    assert data["status"] in ["PENDING_MODERATION", "PUBLISHED", "HIDDEN"]
    assert isinstance(data["version"], int)


def assert_tax_statement(data: dict):
    """PRD 2.4: TaxStatement is an immutable snapshot — carries id and created_at
    but NO updated_at and NO version field."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("family_id", "")), "family_id must be a valid UUID"
    assert is_valid_uuid(data.get("caregiver_id", "")), "caregiver_id must be a valid UUID"
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["cash_wages_cents"], int)
    assert isinstance(data["fica_withheld_cents"], int)
