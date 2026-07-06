"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["home_store_code"], str)


def assert_loyalty_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be UUID"
    assert isinstance(data["points_earned"], int)
    assert isinstance(data["points_redeemed"], int)
    assert isinstance(data["points_balance"], int)
    assert isinstance(data["spend_ytd_cents"], int)
    assert data["tier_forward"] in ["BASIC", "SILVER", "GOLD"]
    assert data["tier_chronological"] in ["BASIC", "SILVER", "GOLD"]
    # Invariant: points_balance == points_earned - points_redeemed.
    assert data["points_balance"] == data["points_earned"] - data["points_redeemed"], (
        "points_balance invariant violated"
    )


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str)
    assert data["sell_mode"] in ["UNIT", "BY_YARD", "BULK"]
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["is_clearance"], bool)
    assert isinstance(data["special_order_only"], bool)


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", ""))
    # Invariant: on_hand == available + reserved.
    assert data["on_hand_yards"] == data["available_yards"] + data["reserved_yards"], (
        "inventory invariant on_hand == available + reserved violated"
    )


def assert_coupon(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str)
    assert data["discount_type"] in ["PERCENT", "FIXED"]


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["fulfillment_status"] in [
        "BUILDING", "SUBMITTED", "READY_FOR_PICKUP", "PICKED_UP", "CANCELLED"
    ]
    assert data["payment_status"] in ["UNPAID", "PAID", "REFUNDED"]


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert data["status"] in ["DRAFT", "RESERVED", "FULFILLED", "CANCELLED"]


def assert_workshop(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "OPEN", "CLOSED", "CANCELLED"]


def assert_workshop_session(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity"], int)
    assert isinstance(data["registered_count"], int)


def assert_workshop_registration(data: dict):
    _assert_common(data)
    assert data["status"] in ["REGISTERED", "WAITLISTED", "CANCELLED"]


def assert_framing_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["QUOTED", "APPROVED", "IN_PRODUCTION", "READY", "CANCELLED"]
    assert isinstance(data["quoted_price_cents"], int)


def assert_special_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["REQUESTED", "QUOTED", "CONFIRMED", "RECEIVED", "CANCELLED"]
