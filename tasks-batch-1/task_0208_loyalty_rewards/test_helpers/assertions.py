"""Entity assertions and domain invariant checkers for the Loyalty Rewards API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version (full-complement entities)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_fields(data: dict):
    """id + created_at only (append-only ledger rows and fixed child records)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must NOT carry updated_at"
    assert "version" not in data, "append-only record must NOT carry version"


def assert_member(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["current_tier_code"] in ("STANDARD", "SILVER", "GOLD", "PLATINUM")
    assert isinstance(data["available_points"], int)
    assert isinstance(data["projected_points"], int)
    assert isinstance(data["qualifying_points_window"], int)
    assert isinstance(data["lifetime_earned_points"], int)
    assert data["available_points"] >= 0, "available_points must be non-negative"


def assert_program(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")


def assert_points_lot(data: dict):
    assert_common_fields(data)
    assert data["source_type"] in (
        "EARN_PURCHASE", "EARN_BONUS", "BIRTHDAY", "REFERRAL", "TRANSFER_IN_REVERSAL"
    )
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED")
    assert data["original_points"] > 0, "original_points must be strictly positive"
    assert data["remaining_points"] >= 0, "remaining_points floored at 0"


def assert_points_transaction(data: dict):
    assert_append_only_fields(data)
    assert data["type"] in (
        "EARN_PURCHASE", "EARN_BONUS", "BIRTHDAY", "REFERRAL",
        "REDEEM", "TRANSFER_OUT", "EXPIRE", "TRANSFER_IN_REVERSAL"
    )
    assert isinstance(data["points_delta"], int)


def assert_redemption(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("QUOTED", "CONFIRMED", "FULFILLED", "CANCELLED")
    assert isinstance(data["quoted_cost_points"], int)


def assert_redemption_line(data: dict):
    assert_append_only_fields(data)
    assert data["quantity"] >= 1
    assert isinstance(data["line_cost_points"], int)


def assert_referral(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "COMPLETED", "EXPIRED", "REVOKED")


def assert_partner_account(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "PAUSED")


def assert_partner_transfer(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "SETTLED", "REVERSED")
    assert isinstance(data["partner_points"], int)


def assert_purchase_event(data: dict):
    assert_common_fields(data)
    assert isinstance(data["earned_points"], int)
    assert isinstance(data["qualifying_points"], int)
