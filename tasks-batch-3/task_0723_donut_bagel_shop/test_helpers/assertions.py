"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str)
    assert data["category"] in ("DONUT", "BAGEL")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 1
    assert isinstance(data["dozen_price_cents"], int) and data["dozen_price_cents"] >= 1
    assert isinstance(data["bulk_threshold"], int) and data["bulk_threshold"] >= 12
    assert isinstance(data["bulk_unit_price_cents"], int) and data["bulk_unit_price_cents"] >= 1
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["allergens"], list)
    assert isinstance(data["active"], bool)


def assert_production_day(data: dict):
    _assert_common(data)
    assert isinstance(data["business_date"], str)
    assert data["status"] in ("OPEN", "BAKING", "SELLING", "CUTOFF", "RECONCILED")
    for field in (
        "gross_sales_cents", "markdown_loss_cents", "waste_cost_cents",
        "expected_full_value_cents", "reconciliation_variance_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be int"


def assert_bake_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["production_day_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["status"] in ("PLANNED", "BAKED", "MARKED_DOWN", "SWEPT")
    assert isinstance(data["par_qty"], int)
    assert isinstance(data["baked_qty"], int)
    assert isinstance(data["remaining_qty"], int) and data["remaining_qty"] >= 0


def assert_retail_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["production_day_id"])
    assert data["status"] in ("CART", "PAID", "VOIDED", "REFUNDED")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] >= 0


def assert_loyalty_account(data: dict):
    _assert_common(data)
    assert isinstance(data["phone"], str)
    assert isinstance(data["punch_count"], int) and data["punch_count"] >= 0
    assert isinstance(data["reward_balance_cents"], int) and data["reward_balance_cents"] >= 0


def assert_wholesale_account(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert 0 <= data["discount_pct"] < 1
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_standing_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["wholesale_account_id"])
    assert 0 <= data["delivery_dow"] <= 6
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")


def assert_wholesale_delivery(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["production_day_id"])
    assert is_valid_uuid(data["standing_order_id"])
    assert data["status"] in ("SCHEDULED", "PICKED", "DELIVERED", "INVOICED", "CANCELLED")
    assert isinstance(data["amount_cents"], int)


def assert_pre_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["wholesale_account_id"])
    assert is_valid_uuid(data["pickup_production_day_id"])
    assert data["status"] in ("REQUESTED", "CONFIRMED", "FULFILLED", "CANCELLED")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["deposit_due_cents"], int)
    assert isinstance(data["deposit_paid_cents"], int)
