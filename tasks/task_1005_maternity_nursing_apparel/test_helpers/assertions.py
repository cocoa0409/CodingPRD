"""Entity assertions and domain invariant checkers.

Uses the framework's generic format checkers internally. LoyaltyLedger is an
immutable audit record — it carries only id + created_at, never updated_at or
version, so assert_ledger_entry does NOT demand those fields.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


VALID_LOYALTY_TIERS = {"BRONZE", "SILVER", "GOLD"}
VALID_PRODUCT_CATEGORIES = {"MATERNITY", "NURSING", "POSTPARTUM", "CAPSULE"}
VALID_PRODUCT_STATUSES = {"ACTIVE", "DISCONTINUED"}
VALID_ORDER_TYPES = {"BUY", "RENTAL"}
VALID_PAYMENT_STATUSES = {"UNPAID", "PAID", "REFUNDED"}
VALID_FULFILLMENT_STATUSES = {"UNFULFILLED", "FULFILLED", "CANCELLED"}
VALID_RENTAL_STATUSES = {"RESERVED", "ACTIVE", "OVERDUE", "RETURNED",
                         "CONVERTED_TO_BUY", "CANCELLED", "LOST"}
VALID_PLAN_TIERS = {"CAPSULE_BASIC", "CAPSULE_PLUS"}
VALID_SUBSCRIPTION_STATUSES = {"ACTIVE", "PAUSED", "CANCELLED"}
VALID_CAPSULE_STATUSES = {"PACKED", "SHIPPED", "VOIDED"}
VALID_RETURN_TYPES = {"REFUND", "STORE_CREDIT", "EXCHANGE"}
VALID_RETURN_STATUSES = {"REQUESTED", "APPROVED", "REJECTED"}
VALID_LEDGER_REASONS = {"EARNED", "REDEEMED", "REVERSAL_REDEEM", "CLAWBACK_EARNED", "ADJUSTMENT"}


def assert_common_fields(data: dict):
    """Every mutable resource carries id (UUID), created_at + updated_at (ISO
    8601), and an integer version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["loyalty_points"], int) and data["loyalty_points"] >= 0
    assert isinstance(data["lifetime_points"], int) and data["lifetime_points"] >= 0
    assert data["loyalty_tier"] in VALID_LOYALTY_TIERS
    assert isinstance(data["current_trimester"], int) and 0 <= data["current_trimester"] <= 3
    assert isinstance(data["store_credit_cents"], int) and data["store_credit_cents"] >= 0


def assert_product(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in VALID_PRODUCT_CATEGORIES
    assert isinstance(data["buy_price_cents"], int)
    assert data["status"] in VALID_PRODUCT_STATUSES


def assert_variant(data: dict):
    assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["size_label"], str)
    assert isinstance(data["trimester_fit"], list)
    assert isinstance(data["inventory_on_hand"], int) and data["inventory_on_hand"] >= 0
    assert isinstance(data["rental_units_total"], int) and data["rental_units_total"] >= 0
    assert isinstance(data["reserved_rental_units"], int) and data["reserved_rental_units"] >= 0
    assert data["status"] in VALID_PRODUCT_STATUSES


def assert_variant_pool_invariant(data: dict):
    """PRD §2.9: rental_units_total == available units + reserved_rental_units,
    so reserved never exceeds total and both are non-negative."""
    assert data["reserved_rental_units"] >= 0
    assert data["rental_units_total"] >= 0
    assert data["reserved_rental_units"] <= data["rental_units_total"], (
        f"reserved {data['reserved_rental_units']} must not exceed total "
        f"{data['rental_units_total']}"
    )


def assert_fit_profile(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["recommended_size"], str) and len(data["recommended_size"]) > 0


def assert_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["variant_id"], str)
    assert data["order_type"] in VALID_ORDER_TYPES
    assert data["payment_status"] in VALID_PAYMENT_STATUSES
    assert data["fulfillment_status"] in VALID_FULFILLMENT_STATUSES
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["grand_total_cents"], int) and data["grand_total_cents"] >= 0


def assert_rental(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["variant_id"], str)
    assert data["status"] in VALID_RENTAL_STATUSES
    assert isinstance(data["provisional_charge_cents"], int)
    assert isinstance(data["final_charge_cents"], int)
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0


def assert_subscription(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert data["plan_tier"] in VALID_PLAN_TIERS
    assert data["status"] in VALID_SUBSCRIPTION_STATUSES
    assert isinstance(data["capsules_shipped"], int) and data["capsules_shipped"] >= 0


def assert_capsule(data: dict):
    assert_common_fields(data)
    assert isinstance(data["subscription_id"], str)
    assert isinstance(data["item_variant_ids"], list)
    assert data["status"] in VALID_CAPSULE_STATUSES
    assert isinstance(data["retail_value_cents"], int) and data["retail_value_cents"] >= 0


def assert_return(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert data["return_type"] in VALID_RETURN_TYPES
    assert data["status"] in VALID_RETURN_STATUSES
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0
    assert isinstance(data["restocking_fee_cents"], int) and data["restocking_fee_cents"] >= 0


def assert_ledger_entry(data: dict):
    """LoyaltyLedger is append-only: id + created_at only (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["reason"] in VALID_LEDGER_REASONS
    assert isinstance(data["points_delta"], int)
    assert isinstance(data["balance_after"], int)
