"""Entity assertions and domain invariant checkers.

Validate response structure against the PRD contract. Generic format helpers
(UUID, ISO 8601) come from the framework.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (common_fields entities). PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_category(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["pricing_model"] in ("HOURLY", "FIXED")
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["default_duration_minutes"], int)


def assert_tasker(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 1000
    assert data["status"] in ("ACTIVE", "RESTRICTED", "SUSPENDED")
    assert isinstance(data["trust_score"], int)
    assert 0 <= data["trust_score"] <= 100
    assert isinstance(data["active_booking_count"], int) and data["active_booking_count"] >= 0
    assert isinstance(data["completed_booking_count"], int)
    assert isinstance(data["rating_count"], int) and data["rating_count"] >= 0
    assert isinstance(data["avg_rating"], (int, float)) and data["avg_rating"] >= 0


def assert_skill(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tasker_id"])
    assert is_valid_uuid(data["category_id"])
    assert data["vetting_status"] in ("PENDING", "VETTED", "REJECTED")


def assert_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tasker_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ("OPEN", "CLOSED")


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["category_id"])
    assert data["dispatch_mode"] in ("SAME_DAY", "SCHEDULED")
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert data["status"] in (
        "DRAFT", "OFFERED", "CLAIMED", "EN_ROUTE", "IN_PROGRESS",
        "COMPLETED", "CANCELLED", "EXPIRED",
    )
    assert isinstance(data["tip_cents"], int) and data["tip_cents"] >= 0


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    for f in ("final_labor_cents", "final_service_fee_cents", "tip_cents",
              "total_charged_cents", "tasker_payout_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
        assert data[f] >= 0, f"{f} must be non-negative"


def assert_cancellation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert data["fee_tier"] in ("FREE", "LATE", "LAST_MINUTE")
    assert isinstance(data["cancellation_fee_cents"], int)
    assert data["cancellation_fee_cents"] >= 0


def assert_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_valid_uuid(data["tasker_id"])
    assert isinstance(data["rating_value"], int) and 1 <= data["rating_value"] <= 5
    assert data["status"] in ("PUBLISHED", "HIDDEN", "REMOVED")


def assert_incident(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tasker_id"])
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert data["status"] in ("OPEN", "UPHELD", "DISMISSED")
    assert isinstance(data["penalty_points"], int)


def assert_series(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["category_id"])
    assert is_valid_uuid(data["tasker_id"])
    assert data["frequency"] in ("WEEKLY", "BIWEEKLY")
    assert data["status"] in ("ACTIVE", "ENDED")
    assert isinstance(data["generated_count"], int)


def assert_chat_message(data: dict):
    """ChatMessage is append-only (common_fields:false): id + created_at ONLY,
    no updated_at, no version. PRD §2.4, §3.8."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["sender_role"] in ("CLIENT", "TASKER")
    assert isinstance(data["body"], str) and 1 <= len(data["body"]) <= 1000
