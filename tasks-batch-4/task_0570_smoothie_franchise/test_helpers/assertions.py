"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_franchisee(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0
    assert isinstance(data["lifetime_royalty_cents"], int)


def assert_store(data: dict):
    _assert_common(data)
    assert data["status"] in {"SETUP", "OPEN", "SUSPENDED", "CLOSED"}
    assert isinstance(data["catering_capacity"], int) and data["catering_capacity"] >= 1
    assert isinstance(data["mtd_spoilage_cents"], int) and data["mtd_spoilage_cents"] >= 0


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert data["status"] in {"AVAILABLE", "DEPLETED", "SPOILED"}
    assert data["remaining_qty"] >= 0
    assert data["consumed_qty"] >= 0
    assert data["spoiled_qty"] >= 0


def assert_customer(data: dict):
    _assert_common(data)
    assert data["loyalty_tier"] in {"BRONZE", "SILVER", "GOLD"}
    assert isinstance(data["points_balance"], int)
    assert isinstance(data["lifetime_points_earned"], int)


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["tier"] in {"BASIC", "PREMIUM"}
    assert data["status"] in {"ACTIVE", "PAST_DUE", "CANCELLED"}
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert isinstance(data["credits_remaining"], int) and data["credits_remaining"] >= 0


def assert_order(data: dict):
    _assert_common(data)
    assert data["fulfillment_status"] in {"PLACED", "PREPARING", "READY", "PICKED_UP", "CANCELLED"}
    assert data["payment_status"] in {"PENDING", "PAID", "REFUNDED"}
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["gross_merch_cents"], int)


def assert_catering_booking(data: dict):
    _assert_common(data)
    assert data["status"] in {"REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED"}
    assert data["fulfillment_type"] in {"PICKUP", "DELIVERY"}
    assert isinstance(data["quoted_price_cents"], int)


def assert_reconciliation(data: dict):
    _assert_common(data)
    assert data["status"] in {"OPEN", "COUNTED", "POSTED"}


def assert_points_transaction(data: dict):
    """PointsTransaction is an append-only ledger event: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["reason"] in {"EARN", "REDEEM", "CLAWBACK", "SUBSCRIPTION_BONUS"}
    assert isinstance(data["delta"], int)


def assert_points_balance_matches_ledger(customer: dict, transactions: list):
    """points_balance equals the sum of delta across all of the customer's ledger entries (§3.3)."""
    ledger_sum = sum(tx["delta"] for tx in transactions)
    assert customer["points_balance"] == ledger_sum, (
        f"points_balance {customer['points_balance']} != ledger sum {ledger_sum}"
    )
