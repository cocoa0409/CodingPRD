"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §3).

These use the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """The id/created_at/updated_at/version quartet carried by all entities
    except PointsLot (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_card_product(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 100
    assert isinstance(data["base_earn_rate_bps"], int)
    assert isinstance(data["signup_bonus_points"], int)
    assert isinstance(data["signup_bonus_spend_threshold_cents"], int)
    assert isinstance(data["signup_bonus_window_days"], int)
    assert isinstance(data["tier_thresholds"], list)
    assert isinstance(data["points_expiry_months"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_transfer_partner(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert data["partner_type"] in ("AIRLINE", "HOTEL")
    assert isinstance(data["transfer_ratio_num"], int) and data["transfer_ratio_num"] >= 1
    assert isinstance(data["transfer_ratio_den"], int) and data["transfer_ratio_den"] >= 1
    assert isinstance(data["min_transfer_points"], int) and data["min_transfer_points"] >= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_card_account(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("card_product_id", "")), "card_product_id must be a UUID"
    assert isinstance(data["cardholder_name"], str)
    assert is_iso8601_timestamp(data.get("opened_at", "")), "opened_at must be ISO 8601"
    assert isinstance(data["points_balance"], int)
    assert isinstance(data["pending_points"], int)
    assert isinstance(data["qualifying_spend_cents"], int)
    assert isinstance(data["annual_spend_cents"], int)
    assert isinstance(data["current_tier_index"], int)
    assert data["signup_bonus_status"] in ("NOT_QUALIFIED", "EARNED", "EXPIRED_UNQUALIFIED")
    assert data["status"] in ("PENDING", "ACTIVE", "CLOSED")


def assert_transaction(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("card_account_id", "")), "card_account_id must be a UUID"
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["category_code"], str)
    assert is_iso8601_timestamp(data.get("transacted_at", "")), "transacted_at must be ISO 8601"
    assert isinstance(data["earned_points"], int)
    assert isinstance(data["quarterly_bonus_applied_cents"], int)
    assert data["status"] in ("PENDING", "POSTED", "DECLINED", "REFUNDED")


def assert_redemption(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("card_account_id", "")), "card_account_id must be a UUID"
    assert data["redemption_type"] in ("STATEMENT_CREDIT", "POINTS_TRANSFER")
    assert isinstance(data["points_requested"], int) and data["points_requested"] >= 1
    assert isinstance(data["redeemed_value"], int)
    assert isinstance(data["lots_consumed"], list)
    assert data["status"] in ("PENDING", "CONFIRMED", "REJECTED", "REVERSED")


def assert_category_activation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("card_account_id", "")), "card_account_id must be a UUID"
    assert is_valid_uuid(data.get("quarterly_category_id", "")), "quarterly_category_id must be a UUID"
    assert is_iso8601_timestamp(data.get("activated_at", "")), "activated_at must be ISO 8601"
    assert data["status"] == "ACTIVE"


def assert_points_lot(data: dict):
    """PointsLot is append-only (PRD §2.4): only id + created_at; no version
    or updated_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("card_account_id", "")), "card_account_id must be a UUID"
    assert data["lot_type"] in ("EARN", "SIGNUP_BONUS")
    assert isinstance(data["original_points"], int)
    assert isinstance(data["remaining_points"], int)
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"
    assert data["status"] in ("ACTIVE", "CONSUMED", "EXPIRED", "CLAWED_BACK")


def assert_points_lot_has_no_version_fields(data: dict):
    """PRD §2.4: a PointsLot has neither an updated_at field nor a version field."""
    assert "version" not in data, "PointsLot must not expose a version field (PRD §2.4)"
    assert "updated_at" not in data, "PointsLot must not expose an updated_at field (PRD §2.4)"
