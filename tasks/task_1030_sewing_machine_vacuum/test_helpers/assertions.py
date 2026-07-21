"""Entity assertions and domain invariant checkers for the PRD contract."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """Fields every entity carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1 int"


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["model_name"], str) and data["model_name"]
    assert data["category"] in ["SEWING_MACHINE", "VACUUM", "PART", "ACCESSORY"]
    assert isinstance(data["brand"], str)
    assert isinstance(data["msrp_cents"], int) and data["msrp_cents"] >= 0
    assert isinstance(data["warranty_months"], int) and data["warranty_months"] >= 0
    assert data["recall_status"] in ["NONE", "RECALLED"]


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["store_credit_cents"], int)
    assert isinstance(data["lifetime_spend_cents"], int)
    assert data["loyalty_tier"] in ["STANDARD", "GOLD", "PLATINUM"]


def assert_inventory_item(data: dict):
    _assert_common(data)
    assert isinstance(data["product_id"], str)
    assert data["condition"] in ["NEW", "REFURBISHED", "USED_TRADE_IN"]
    assert isinstance(data["acquisition_cost_cents"], int) and data["acquisition_cost_cents"] >= 0
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert data["status"] in ["IN_STOCK", "RESERVED", "SOLD", "SCRAPPED"]


def assert_sales_order(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["inventory_item_id"], str)
    assert isinstance(data["sale_price_cents"], int) and data["sale_price_cents"] >= 0
    assert data["status"] in ["RESERVED", "COMPLETED", "CANCELLED"]


def assert_repair_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["is_warranty"], bool)
    assert data["status"] in [
        "INTAKE", "AWAITING_APPROVAL", "IN_REPAIR", "READY", "CLOSED", "CANCELLED",
    ]


def assert_rental_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["inventory_item_id"], str)
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["status"] in ["ACTIVE", "RETURNED", "CANCELLED"]


def assert_class_session(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str)
    assert data["machine_type"] in ["SEWING", "VACUUM"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["waitlist_count"], int) and data["waitlist_count"] >= 0
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_class_enrollment(data: dict):
    _assert_common(data)
    assert isinstance(data["class_session_id"], str)
    assert isinstance(data["customer_id"], str)
    assert data["status"] in ["ENROLLED", "WAITLISTED", "ATTENDED", "CANCELLED"]


def assert_tune_up_subscription(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert data["plan_tier"] in ["BASIC", "PRO"]
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["tune_ups_included"], int) and data["tune_ups_included"] >= 0
    assert isinstance(data["tune_ups_used"], int) and data["tune_ups_used"] >= 0
    assert data["status"] in ["ACTIVE", "PAST_DUE", "CANCELLED"]


def assert_special_order(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["status"] in ["REQUESTED", "RECEIVED", "FULFILLED", "CANCELLED"]
