"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def assert_customer(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"customer.id not a UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "customer.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "customer.updated_at must be ISO 8601"
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["delivery_zone"] in ("ZONE_A", "ZONE_B", "ZONE_C")
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD", "PLATINUM")
    assert isinstance(data["points_balance"], int)
    assert isinstance(data["lifetime_points_earned"], int)
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0
    assert data["lifetime_points_earned"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 0


def assert_plant(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"plant.id not a UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["light_tag"] in ("LOW", "MEDIUM", "BRIGHT_INDIRECT", "DIRECT")
    assert data["care_tag"] in ("EASY", "MODERATE", "EXPERT")
    assert data["weight_class"] in ("LIGHT", "STANDARD", "HEAVY")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 100
    assert isinstance(data["warranty_days"], int) and data["warranty_days"] >= 0
    assert isinstance(data["available_count"], int) and data["available_count"] >= 0


def assert_stock_unit(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("plant_id", ""))
    assert data["health_status"] in ("HEALTHY", "RECOVERING", "DECLINING", "DEAD")
    assert data["sale_status"] in ("FOR_SALE", "RESERVED", "SOLD", "SHRINK", "RETURNED")
    assert data["shrink_reason"] in ("NONE", "MORTALITY", "DAMAGED", "EXPIRED_HOLD", "WARRANTY_RETURN")


def assert_care_log_entry(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("stock_unit_id", ""))
    assert data["entry_type"] in ("WATER", "LIGHT_CHECK", "PRUNE", "REPOT", "OBSERVATION", "SHRINK_DECLARE")
    assert data.get("actor_role") in ("Horticulturist", "Manager")
    # Append-only: no version, no updated_at asserted
    assert is_iso8601_timestamp(data.get("entered_at", ""))


def assert_delivery_driver(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["daily_capacity_minutes"], int) and data["daily_capacity_minutes"] > 0


def assert_order(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["fulfillment_status"] in ("PENDING", "DISPATCHED", "DELIVERED", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["delivery_zone"] in ("ZONE_A", "ZONE_B", "ZONE_C")
    assert isinstance(data["gift_flag"], bool)
    assert isinstance(data["applied_redemption_cents"], int) and data["applied_redemption_cents"] >= 0
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["delivery_fee_cents"], int) and data["delivery_fee_cents"] >= 0
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["points_provisional"], int)
    assert isinstance(data["points_finalized"], int)


def assert_order_line(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("plant_id", ""))
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_subtotal_cents"], int)
    assert data["refund_status"] in ("NONE", "PENDING_REVIEW", "REFUNDED", "DENIED")
    assert isinstance(data["refund_amount_cents"], int) and data["refund_amount_cents"] >= 0


def assert_delivery_assignment(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("driver_id", ""))
    assert is_iso8601_timestamp(data.get("window_start_at", ""))
    assert is_iso8601_timestamp(data.get("window_end_at", ""))
    assert data["status"] in ("SCHEDULED", "DELIVERED", "FAILED")


def assert_subscription(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["plan_tier"] in ("STARTER", "CLASSIC", "CURATOR")
    assert data["care_tag_preference"] in ("EASY", "MODERATE", "EXPERT")
    assert data["light_tag_preference"] in ("LOW", "MEDIUM", "BRIGHT_INDIRECT", "DIRECT")
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED", "MISSING_STOCK")
    assert is_iso8601_timestamp(data.get("next_fulfillment_at", ""))
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] > 0


def assert_workshop(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["topic"] in ("REPOTTING", "LIGHT_101", "PROPAGATION", "PEST_CONTROL")
    assert data["room_id"] in ("STUDIO_A", "STUDIO_B")
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_workshop_registration(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("workshop_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["status"] in ("REGISTERED", "ATTENDED", "CANCELLED")


def assert_warranty_claim(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("orderline_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["reason"] in ("MORTALITY", "DAMAGED", "MISDELIVERY", "OTHER")
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED")
    assert isinstance(data["refund_amount_cents_provisional"], int) and data["refund_amount_cents_provisional"] >= 0
    assert isinstance(data["refund_amount_cents_final"], int) and data["refund_amount_cents_final"] >= 0


def assert_special_order(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["service_type"] in ("PROCUREMENT", "REPOTTING")
    assert data["status"] in ("REQUESTED", "QUOTED", "RE_QUOTED", "CUSTOMER_APPROVED", "FULFILLED", "CANCELLED")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_loyalty_ledger_entry(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["reason"] in ("ACCRUAL_PROVISIONAL", "ACCRUAL_FINAL_DELTA", "REVERSAL", "REDEMPTION", "MANUAL_ADJUST")
    assert isinstance(data["delta_points"], int)
    assert is_iso8601_timestamp(data.get("recorded_at", ""))
