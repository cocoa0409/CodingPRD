"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["throughput_capacity_per_slot"], int)
    assert data["throughput_capacity_per_slot"] >= 1
    assert data["locker_count"] >= 0
    assert data["queue_status"] in ("OPEN", "BUSY", "SURGE")
    assert isinstance(data["is_active"], bool)


def assert_menu_item(data: dict):
    _assert_common(data)
    assert data["base_price_cents"] >= 0
    assert data["base_calories"] >= 0
    assert isinstance(data["allergen_tags"], list)
    assert isinstance(data["is_available"], bool)


def assert_pickup_slot(data: dict):
    _assert_common(data)
    assert data["channel"] in ("COUNTER", "LOCKER", "DELIVERY")
    assert data["reserved_count"] >= 0
    assert isinstance(data["is_closed"], bool)


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["allergen_blocklist"], list)
    assert data["wallet_credit_cents"] >= 0


def assert_loyalty_account(data: dict):
    _assert_common(data)
    assert data["points_balance"] >= 0, "points_balance never negative"
    assert data["lifetime_points_earned"] >= 0
    assert data["tier"] in ("GREEN", "GOLD", "PLATINUM")


def assert_order(data: dict):
    _assert_common(data)
    assert data["order_status"] in (
        "CART", "PLACED", "PREPARING", "READY", "COMPLETED", "CANCELLED",
    )
    assert data["settlement_status"] in (
        "UNSETTLED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED",
    )
    assert data["channel"] in ("COUNTER", "LOCKER", "DELIVERY")
    assert data["total_cents"] >= 0, "total_cents floored at 0"
    assert data["refunded_cents"] <= data["total_cents"] or data["total_cents"] == 0


def assert_order_line(data: dict):
    _assert_common(data)
    assert data["quantity"] >= 1
    assert isinstance(data["modifier_ids"], list)
    assert isinstance(data["effective_allergen_tags"], list)
    assert data["line_calories"] >= 0, "line_calories floored at 0"


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING_PAYMENT", "ACTIVE", "PAST_DUE", "CANCELLED")


def assert_loyalty_challenge(data: dict):
    _assert_common(data)
    assert data["status"] in ("IN_PROGRESS", "ROUND_COMPLETE", "EXPIRED")
    assert data["progress_count"] >= 0
    assert data["rounds_completed"] >= 0


def assert_points_ledger_entry(data: dict):
    """PointsLedgerEntry is append-only: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["reason"] in ("EARN", "REDEEM", "CHALLENGE_BONUS", "CLAWBACK", "ADJUSTMENT")
