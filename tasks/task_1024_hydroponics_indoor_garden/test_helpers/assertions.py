"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response shape and field types against the PRD
contract. Domain invariant helpers check relationships that must always hold.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku_code"], str) and data["sku_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in ["SYSTEM", "LIGHTING", "NUTRIENT", "CONSUMABLE", "ACCESSORY"]
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["is_hazmat"], bool)
    assert isinstance(data["warranty_months"], int) and data["warranty_months"] >= 0
    assert isinstance(data["is_subscribable"], bool)
    assert isinstance(data["reorder_threshold"], int) and data["reorder_threshold"] >= 0
    assert isinstance(data["unit_weight_g"], int) and data["unit_weight_g"] >= 0
    assert isinstance(data["total_available_units"], int) and data["total_available_units"] >= 0
    assert isinstance(data["reorder_flag"], bool)


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["quantity_on_hand"], int) and data["quantity_on_hand"] >= 0
    assert isinstance(data["quantity_reserved"], int) and data["quantity_reserved"] >= 0
    assert isinstance(data["quantity_available"], int)
    assert data["quantity_available"] == data["quantity_on_hand"] - data["quantity_reserved"]
    assert data["status"] in ["ACTIVE", "DEPLETED", "QUARANTINED"]


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert isinstance(data["loyalty_points"], int) and data["loyalty_points"] >= 0
    assert data["loyalty_tier"] in ["BRONZE", "SILVER", "GOLD"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_commercial_account(data: dict):
    _assert_common(data)
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] > 0
    assert isinstance(data["credit_used_cents"], int) and data["credit_used_cents"] >= 0
    assert isinstance(data["payment_terms_net_days"], int) and data["payment_terms_net_days"] >= 0
    assert data["discount_tier"] in ["STANDARD", "SILVER", "GOLD"]
    assert data["status"] in ["PENDING", "ACTIVE", "ON_HOLD", "SUSPENDED"]


def assert_order(data: dict):
    _assert_common(data)
    assert data["order_type"] in ["RETAIL", "COMMERCIAL"]
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int) and data["discount_cents"] >= 0
    assert isinstance(data["hazmat_surcharge_cents"], int) and data["hazmat_surcharge_cents"] >= 0
    assert isinstance(data["provisional_total_cents"], int)
    assert data["fulfillment_status"] in ["DRAFT", "CONFIRMED", "SHIPPED", "CANCELLED"]
    assert data["payment_status"] in ["UNPAID", "PAID", "REFUNDED"]


def assert_subscription(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["interval_days"], int) and data["interval_days"] > 0
    assert isinstance(data["quantity_per_cycle"], int) and data["quantity_per_cycle"] > 0
    assert isinstance(data["price_locked_cents"], int)
    assert data["status"] in ["ACTIVE", "PAUSED", "CANCELLED"]


def assert_consultant(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["specialty"], str)
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_consult_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["consultant_id"])
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["estimated_fee_cents"], int) and data["estimated_fee_cents"] >= 0
    assert data["status"] in ["REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED"]


def assert_room(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] > 0


def assert_workshop_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["room_id"])
    assert isinstance(data["title"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["seats_taken"], int) and data["seats_taken"] >= 0
    assert data["status"] in ["SCHEDULED", "OPEN", "COMPLETED", "CANCELLED"]


def assert_workshop_registration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["status"] in ["REGISTERED", "WAITLISTED", "CANCELLED"]


def assert_rma(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["return_quantity"], int) and data["return_quantity"] > 0
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "REJECTED"]
