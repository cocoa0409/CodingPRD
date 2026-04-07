"""
Entity assertion helpers for the e-commerce marketplace test suite.

Each assert_<entity>(data) function validates the structural shape and value
constraints of an entity dict returned by the API.  Domain invariant checkers
verify cross-field business rules.

All functions use generic helpers from prd_bench_local_runner.testing.
"""

import pytest

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)

# ─── Enum value sets ─────────────────────────────────────

SHOP_STATUSES = {"PENDING_REVIEW", "ACTIVE", "SUSPENDED", "CLOSED"}
PRODUCT_STATUSES = {"DRAFT", "LISTED", "DELISTED", "ARCHIVED"}
PROMOTION_STATUSES = {"DRAFT", "ACTIVE", "PAUSED", "EXPIRED", "CANCELLED"}
PROMO_TYPES = {"PERCENTAGE", "FIXED_AMOUNT", "BUY_X_GET_Y_FREE"}
PAYMENT_METHODS = {"CREDIT_CARD", "DEBIT_CARD", "WALLET", "BANK_TRANSFER"}
PAYMENT_TYPES = {"CHARGE", "REFUND"}
PAYMENT_STATUSES = {"PENDING", "SUCCESS", "FAILED"}
ORDER_STATUSES = {"CREATED", "CONFIRMED", "COMPLETED", "CANCELLED"}
PAYMENT_ORDER_STATUSES = {"UNPAID", "PAYING", "PAID", "PARTIAL_REFUND", "FULL_REFUND"}
FULFILLMENT_STATUSES = {"PENDING", "PROCESSING", "SHIPPED", "DELIVERED"}
REFUND_TYPES = {"FULL", "PARTIAL"}
REFUND_STATUSES = {"REQUESTED", "APPROVED", "PROCESSED", "REJECTED"}
SETTLEMENT_STATUSES = {"DRAFT", "PENDING_APPROVAL", "APPROVED", "PAID", "DISPUTED"}


# ─── Entity Assertions ──────────────────────────────────

def assert_shop(data: dict) -> None:
    """Validate the shape and constraints of a Shop entity."""
    assert is_valid_uuid(data["id"]), f"Shop id is not a valid UUID: {data['id']}"
    assert isinstance(data["shop_name"], str) and len(data["shop_name"]) > 0
    assert isinstance(data["owner_id"], str) and len(data["owner_id"]) > 0
    assert data["status"] in SHOP_STATUSES, (
        f"Invalid shop status: {data['status']}"
    )
    assert isinstance(data["monthly_gmv"], (int, float)) and data["monthly_gmv"] >= 0
    assert isinstance(data["settlement_balance"], (int, float)) and data["settlement_balance"] >= 0
    assert is_iso8601_timestamp(data["created_at"]), f"Invalid created_at: {data['created_at']}"
    assert is_iso8601_timestamp(data["updated_at"]), f"Invalid updated_at: {data['updated_at']}"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_product(data: dict) -> None:
    """Validate the shape and constraints of a Product entity."""
    assert is_valid_uuid(data["id"]), f"Product id is not a valid UUID: {data['id']}"
    assert is_valid_uuid(data["shop_id"]), f"Product shop_id is not a valid UUID: {data['shop_id']}"
    assert isinstance(data["product_name"], str) and len(data["product_name"]) > 0
    assert isinstance(data["category"], str) and len(data["category"]) > 0
    assert isinstance(data["base_price"], (int, float)) and data["base_price"] > 0
    assert isinstance(data["inventory_count"], int) and data["inventory_count"] >= 0
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert isinstance(data["available_count"], int) and data["available_count"] >= 0
    assert data["status"] in PRODUCT_STATUSES, (
        f"Invalid product status: {data['status']}"
    )
    assert is_iso8601_timestamp(data["created_at"]), f"Invalid created_at: {data['created_at']}"
    assert is_iso8601_timestamp(data["updated_at"]), f"Invalid updated_at: {data['updated_at']}"
    assert isinstance(data["version"], int) and data["version"] >= 1

    # Derived field invariant
    assert data["available_count"] == data["inventory_count"] - data["reserved_count"], (
        f"available_count ({data['available_count']}) != "
        f"inventory_count ({data['inventory_count']}) - reserved_count ({data['reserved_count']})"
    )


def assert_promotion(data: dict) -> None:
    """Validate the shape and constraints of a Promotion entity."""
    assert is_valid_uuid(data["id"]), f"Promotion id is not a valid UUID: {data['id']}"
    assert is_valid_uuid(data["shop_id"]), f"Promotion shop_id is not a valid UUID: {data['shop_id']}"
    assert isinstance(data["promo_name"], str) and len(data["promo_name"]) > 0
    assert data["promo_type"] in PROMO_TYPES, (
        f"Invalid promo_type: {data['promo_type']}"
    )
    assert isinstance(data["promo_value"], (int, float)) and data["promo_value"] > 0
    assert isinstance(data["promo_threshold"], int) and data["promo_threshold"] >= 0
    if data.get("max_discount_cap") is not None:
        assert isinstance(data["max_discount_cap"], (int, float)) and data["max_discount_cap"] > 0
    assert isinstance(data["stackable"], bool)
    assert isinstance(data["priority"], int)
    assert isinstance(data["applicable_categories"], list)
    assert is_iso8601_timestamp(data["start_time"]), f"Invalid start_time: {data['start_time']}"
    assert is_iso8601_timestamp(data["end_time"]), f"Invalid end_time: {data['end_time']}"
    assert isinstance(data["usage_count"], int) and data["usage_count"] >= 0
    if data.get("max_usage") is not None:
        assert isinstance(data["max_usage"], int) and data["max_usage"] > 0
    assert data["status"] in PROMOTION_STATUSES, (
        f"Invalid promotion status: {data['status']}"
    )
    assert is_iso8601_timestamp(data["created_at"]), f"Invalid created_at: {data['created_at']}"
    assert is_iso8601_timestamp(data["updated_at"]), f"Invalid updated_at: {data['updated_at']}"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_order(data: dict) -> None:
    """Validate the shape and constraints of an Order entity."""
    assert is_valid_uuid(data["id"]), f"Order id is not a valid UUID: {data['id']}"
    assert is_valid_uuid(data["shop_id"]), f"Order shop_id is not a valid UUID: {data['shop_id']}"
    assert isinstance(data["customer_id"], str) and len(data["customer_id"]) > 0
    assert isinstance(data["subtotal"], (int, float)) and data["subtotal"] >= 0
    assert isinstance(data["discount_amount"], (int, float)) and data["discount_amount"] >= 0
    assert isinstance(data["total_amount"], (int, float)) and data["total_amount"] >= 0.01
    assert data["payment_status"] in PAYMENT_ORDER_STATUSES, (
        f"Invalid payment_status: {data['payment_status']}"
    )
    assert data["fulfillment_status"] in FULFILLMENT_STATUSES, (
        f"Invalid fulfillment_status: {data['fulfillment_status']}"
    )
    assert data["order_status"] in ORDER_STATUSES, (
        f"Invalid order_status: {data['order_status']}"
    )
    assert isinstance(data["applied_promotions"], list)
    assert is_iso8601_timestamp(data["created_at"]), f"Invalid created_at: {data['created_at']}"
    assert is_iso8601_timestamp(data["updated_at"]), f"Invalid updated_at: {data['updated_at']}"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_order_item(data: dict) -> None:
    """Validate the shape and constraints of an OrderItem entity."""
    assert is_valid_uuid(data["id"]), f"OrderItem id is not a valid UUID: {data['id']}"
    assert is_valid_uuid(data["order_id"]), f"OrderItem order_id is not a valid UUID: {data['order_id']}"
    assert is_valid_uuid(data["product_id"]), f"OrderItem product_id is not a valid UUID: {data['product_id']}"

    # Product snapshot
    snapshot = data["product_snapshot"]
    assert isinstance(snapshot, dict), "product_snapshot must be a dict"
    assert isinstance(snapshot.get("product_name"), str) and len(snapshot["product_name"]) > 0
    assert isinstance(snapshot.get("base_price"), (int, float)) and snapshot["base_price"] > 0
    assert isinstance(snapshot.get("category"), str) and len(snapshot["category"]) > 0

    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price"], (int, float)) and data["unit_price"] > 0
    assert isinstance(data["line_total"], (int, float))
    assert isinstance(data["discount_share"], (int, float)) and data["discount_share"] >= 0
    assert isinstance(data["final_price"], (int, float)) and data["final_price"] >= 0


def assert_payment(data: dict) -> None:
    """Validate the shape and constraints of a Payment entity."""
    assert is_valid_uuid(data["id"]), f"Payment id is not a valid UUID: {data['id']}"
    assert is_valid_uuid(data["order_id"]), f"Payment order_id is not a valid UUID: {data['order_id']}"
    assert data["payment_method"] in PAYMENT_METHODS, (
        f"Invalid payment_method: {data['payment_method']}"
    )
    assert isinstance(data["amount"], (int, float)) and data["amount"] > 0
    assert isinstance(data["transaction_ref"], str) and len(data["transaction_ref"]) > 0
    assert data["payment_type"] in PAYMENT_TYPES, (
        f"Invalid payment_type: {data['payment_type']}"
    )
    assert data["status"] in PAYMENT_STATUSES, (
        f"Invalid payment status: {data['status']}"
    )
    assert is_iso8601_timestamp(data["created_at"]), f"Invalid created_at: {data['created_at']}"


def assert_refund(data: dict) -> None:
    """Validate the shape and constraints of a Refund entity."""
    assert is_valid_uuid(data["id"]), f"Refund id is not a valid UUID: {data['id']}"
    assert is_valid_uuid(data["order_id"]), f"Refund order_id is not a valid UUID: {data['order_id']}"
    assert isinstance(data["reason"], str) and len(data["reason"]) > 0
    assert data["refund_type"] in REFUND_TYPES, (
        f"Invalid refund_type: {data['refund_type']}"
    )
    if data["refund_type"] == "PARTIAL":
        assert isinstance(data["refund_items"], list) and len(data["refund_items"]) > 0, (
            "PARTIAL refund must have non-empty refund_items"
        )
    assert isinstance(data["refund_subtotal"], (int, float)) and data["refund_subtotal"] >= 0
    assert isinstance(data["refund_discount_share"], (int, float)) and data["refund_discount_share"] >= 0
    assert isinstance(data["refund_amount"], (int, float)) and data["refund_amount"] >= 0
    assert isinstance(data["inventory_restored"], bool)
    assert data["status"] in REFUND_STATUSES, (
        f"Invalid refund status: {data['status']}"
    )
    assert is_iso8601_timestamp(data["created_at"]), f"Invalid created_at: {data['created_at']}"
    assert is_iso8601_timestamp(data["updated_at"]), f"Invalid updated_at: {data['updated_at']}"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_settlement(data: dict) -> None:
    """Validate the shape and constraints of a Settlement entity."""
    assert is_valid_uuid(data["id"]), f"Settlement id is not a valid UUID: {data['id']}"
    assert is_valid_uuid(data["shop_id"]), f"Settlement shop_id is not a valid UUID: {data['shop_id']}"
    assert is_iso8601_timestamp(data["period_start"]), f"Invalid period_start: {data['period_start']}"
    assert is_iso8601_timestamp(data["period_end"]), f"Invalid period_end: {data['period_end']}"
    assert isinstance(data["gross_amount"], (int, float))
    assert isinstance(data["total_commission"], (int, float))
    assert isinstance(data["total_refunds"], (int, float))
    assert isinstance(data["net_amount"], (int, float))
    assert data["status"] in SETTLEMENT_STATUSES, (
        f"Invalid settlement status: {data['status']}"
    )
    assert is_iso8601_timestamp(data["created_at"]), f"Invalid created_at: {data['created_at']}"
    assert is_iso8601_timestamp(data["updated_at"]), f"Invalid updated_at: {data['updated_at']}"
    assert isinstance(data["version"], int) and data["version"] >= 1


# ─── Domain Invariant Checkers ───────────────────────────

def assert_shop_invariants(shop: dict) -> None:
    """
    Verify cross-field business rules on a Shop entity.

    - settlement_balance >= 0
    - monthly_gmv >= 0
    - Both monetary fields have at most 2 decimal places
    """
    assert shop["settlement_balance"] >= 0, (
        f"settlement_balance must be >= 0, got {shop['settlement_balance']}"
    )
    assert shop["monthly_gmv"] >= 0, (
        f"monthly_gmv must be >= 0, got {shop['monthly_gmv']}"
    )
    assert_cost_precision(shop["settlement_balance"])
    assert_cost_precision(shop["monthly_gmv"])


def assert_order_invariants(order: dict) -> None:
    """
    Verify cross-field business rules on an Order entity.

    - total_amount >= 0.01
    - discount_amount >= 0
    - subtotal >= total_amount + discount_amount (approximately, due to flooring)
    - All monetary fields have at most 2 decimal places
    """
    assert order["total_amount"] >= 0.01, (
        f"total_amount must be >= 0.01, got {order['total_amount']}"
    )
    assert order["discount_amount"] >= 0, (
        f"discount_amount must be >= 0, got {order['discount_amount']}"
    )
    # subtotal = total_amount + discount_amount (total_amount may be floored to 0.01)
    expected_subtotal = order["total_amount"] + order["discount_amount"]
    assert order["subtotal"] == pytest.approx(expected_subtotal, abs=0.01), (
        f"subtotal ({order['subtotal']}) != total_amount ({order['total_amount']}) "
        f"+ discount_amount ({order['discount_amount']})"
    )
    assert_cost_precision(order["subtotal"])
    assert_cost_precision(order["discount_amount"])
    assert_cost_precision(order["total_amount"])


def assert_inventory_consistency(product: dict) -> None:
    """
    Verify inventory invariants on a Product entity.

    - available_count == inventory_count - reserved_count
    - All counts >= 0
    """
    assert product["inventory_count"] >= 0, (
        f"inventory_count must be >= 0, got {product['inventory_count']}"
    )
    assert product["reserved_count"] >= 0, (
        f"reserved_count must be >= 0, got {product['reserved_count']}"
    )
    assert product["available_count"] >= 0, (
        f"available_count must be >= 0, got {product['available_count']}"
    )
    assert product["available_count"] == product["inventory_count"] - product["reserved_count"], (
        f"available_count ({product['available_count']}) != "
        f"inventory_count ({product['inventory_count']}) - reserved_count ({product['reserved_count']})"
    )
