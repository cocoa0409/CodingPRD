"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Generic format checks come from the framework.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_customer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["home_zone"] in ["Z1", "Z2", "Z3", "Z4"]
    assert data["status"] in ["ACTIVE", "DORMANT", "WON_BACK"]
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert isinstance(data["loyalty_points_balance"], int) and data["loyalty_points_balance"] >= 0
    assert isinstance(data["churn_risk_score"], int) and 0 <= data["churn_risk_score"] <= 100
    assert data["churn_band"] in ["OK", "AT_RISK", "CHURN_IMMINENT"]
    assert isinstance(data["version"], int)


def assert_sku(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in ["HOT_SAUCE", "COFFEE", "SNACK"]
    assert data["storage_class"] in ["AMBIENT", "PERISHABLE"]
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 1
    assert isinstance(data["allergens"], list)
    assert data["status"] in ["DRAFT", "ACTIVE", "LABEL_HOLD", "DISCONTINUED"]
    assert isinstance(data["label_approved"], bool)
    assert isinstance(data["available_units"], int) and data["available_units"] >= 0
    assert isinstance(data["version"], int)


def assert_lot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["sku_id"], str)
    assert isinstance(data["lot_code"], str)
    assert isinstance(data["produced_units"], int) and data["produced_units"] >= 1
    assert isinstance(data["remaining_units"], int) and data["remaining_units"] >= 0
    assert data["status"] in ["QUARANTINE", "RELEASED", "EXPIRED", "RECALLED"]
    assert isinstance(data["version"], int)


def assert_subscription(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["sku_id"], str)
    assert data["tier"] in ["STARTER", "CLASSIC", "RESERVE"]
    assert data["cadence_days"] in [14, 28, 56]
    assert data["status"] in ["ACTIVE", "PAUSED", "CANCELLED"]
    assert isinstance(data["consecutive_skip_count"], int) and data["consecutive_skip_count"] >= 0
    assert isinstance(data["version"], int)


def assert_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["customer_id"], str)
    assert data["order_kind"] in ["ONE_TIME", "SUBSCRIPTION", "GIFT", "CORPORATE_BULK"]
    assert data["ship_zone"] in ["Z1", "Z2", "Z3", "Z4"]
    assert data["payment_status"] in ["UNPAID", "PAID", "FAILED", "REFUNDED"]
    assert data["fulfillment_status"] in ["DRAFT", "RESERVED", "SHIPPED", "DELIVERED", "CANCELLED"]
    assert isinstance(data["version"], int)


def assert_order_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["order_id"], str)
    assert isinstance(data["sku_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["line_status"] in ["PENDING", "COMMITTED", "RELEASED"]


def assert_bulk_quote(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["corporate_buyer_id"], str)
    assert isinstance(data["sku_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ["DRAFT", "QUOTED", "ACCEPTED", "EXPIRED"]
    assert isinstance(data["version"], int)


def assert_referral(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["referrer_id"], str)
    assert isinstance(data["referred_id"], str)
    assert data["status"] in ["PENDING", "QUALIFIED", "REWARDED", "VOID"]
    assert isinstance(data["version"], int)


def assert_winback_offer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["customer_id"], str)
    assert data["status"] in ["OFFERED", "REDEEMED", "EXPIRED"]
    assert isinstance(data["version"], int)
