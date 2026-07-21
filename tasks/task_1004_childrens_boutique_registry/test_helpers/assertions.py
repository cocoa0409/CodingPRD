"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


VALID_LOYALTY_TIERS = {"BRONZE", "SILVER", "GOLD", "PLATINUM"}
VALID_SKU_CATEGORIES = {"CLOTHING", "GEAR", "TOY", "FEEDING", "NURSERY"}
VALID_SIZE_STAGES = {"NEWBORN", "M0_3", "M3_6", "M6_12", "M12_24", "T2", "T3", "T4"}
VALID_AVAILABILITY = {"IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK"}
VALID_REGISTRY_STATUSES = {"DRAFT", "ACTIVE", "COMPLETION_UNLOCKED", "ARCHIVED"}
VALID_REGISTRY_KINDS = {"BABY_REGISTRY", "WISHLIST"}
VALID_PAYMENT_STATUSES = {"UNPAID", "PAID", "REFUNDED"}
VALID_FULFILLMENT_STATUSES = {"RESERVED", "READY", "PICKED_UP", "CANCELLED"}
VALID_SHELF_STATUSES = {"OPEN", "CLOSED"}
VALID_CONSIGNMENT_STATUSES = {"RECEIVED", "ON_DISPLAY", "SOLD"}
VALID_TRADE_IN_STATUSES = {"SUBMITTED", "ACCEPTED", "REJECTED"}
VALID_SPECIAL_ORDER_STATUSES = {"REQUESTED", "ALLOCATED", "WAITLISTED", "FULFILLED", "CANCELLED"}


def assert_common_fields(data: dict):
    """Every persisted resource carries id (UUID), created_at, updated_at
    (ISO 8601), and an integer version starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_store(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["open_minute"], int)
    assert isinstance(data["close_minute"], int)
    assert isinstance(data["pickup_station_count"], int)


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["lifetime_spend_cents"], int) and data["lifetime_spend_cents"] >= 0
    assert isinstance(data["store_credit_balance_cents"], int) and data["store_credit_balance_cents"] >= 0
    assert isinstance(data["loyalty_points"], int) and data["loyalty_points"] >= 0
    assert data["loyalty_tier"] in VALID_LOYALTY_TIERS


def assert_sku(data: dict):
    assert_common_fields(data)
    assert isinstance(data["store_id"], str)
    assert data["category"] in VALID_SKU_CATEGORIES
    assert data["size_stage"] in VALID_SIZE_STAGES
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert data["availability_status"] in VALID_AVAILABILITY


def assert_registry(data: dict):
    assert_common_fields(data)
    assert data["kind"] in VALID_REGISTRY_KINDS
    assert data["status"] in VALID_REGISTRY_STATUSES
    assert isinstance(data["desired_value_cents"], int)
    assert isinstance(data["fulfilled_value_cents"], int)
    assert isinstance(data["completion_pct"], (int, float))


def assert_registry_item(data: dict):
    assert_common_fields(data)
    assert isinstance(data["registry_id"], str)
    assert isinstance(data["sku_id"], str)
    assert isinstance(data["desired_qty"], int)
    assert isinstance(data["fulfilled_qty"], int) and data["fulfilled_qty"] >= 0


def assert_registry_gift(data: dict):
    assert_common_fields(data)
    assert isinstance(data["registry_id"], str)
    assert isinstance(data["registry_item_id"], str)
    assert isinstance(data["gifter_customer_id"], str)
    assert isinstance(data["qty"], int)
    assert isinstance(data["amount_cents"], int)


def assert_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["store_id"], str)
    assert data["payment_status"] in VALID_PAYMENT_STATUSES
    assert data["fulfillment_status"] in VALID_FULFILLMENT_STATUSES
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["applied_discount_cents"], int)
    assert isinstance(data["total_before_credit_cents"], int)
    assert isinstance(data["amount_due_cents"], int)


def assert_consignment_shelf(data: dict):
    assert_common_fields(data)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["capacity"], int)
    assert data["status"] in VALID_SHELF_STATUSES


def assert_consignment_item(data: dict):
    assert_common_fields(data)
    assert isinstance(data["consignor_customer_id"], str)
    assert data["status"] in VALID_CONSIGNMENT_STATUSES
    assert isinstance(data["payout_cents"], int)


def assert_trade_in(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["sku_id"], str)
    assert data["status"] in VALID_TRADE_IN_STATUSES
    assert isinstance(data["quoted_value_cents"], int)
    assert isinstance(data["final_value_cents"], int)


def assert_special_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["sku_id"], str)
    assert data["status"] in VALID_SPECIAL_ORDER_STATUSES
