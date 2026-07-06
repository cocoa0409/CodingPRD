"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_mutable_common(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_product(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["category"] in ["BREAD", "PASTRY", "CAKE", "SANDWICH", "OTHER"]
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]
    assert isinstance(data["allergens"], list)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["shelf_life_hours"], int) and data["shelf_life_hours"] >= 1


def assert_oven(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_bake_plan(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in ["DRAFT", "COMMITTED", "BAKED", "RECONCILED", "CLOSED"]


def assert_bake_plan_line(data: dict):
    _assert_mutable_common(data)
    assert_par_partition(data)


def assert_par_partition(data: dict):
    """PRD 2.7: reserved_qty + available_qty == par_qty at all times, available never negative."""
    assert data["available_qty"] >= 0, "available_qty must never be negative"
    assert data["reserved_qty"] + data["available_qty"] == data["par_qty"], (
        f"par partition broken: reserved {data['reserved_qty']} + available "
        f"{data['available_qty']} != par {data['par_qty']}"
    )


def assert_bake_lot(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in ["FRESH", "MARKED_DOWN", "SOLD_OUT", "EXPIRED"]
    assert is_iso8601_timestamp(data.get("best_by", "")), "best_by must be ISO 8601"


def assert_wholesale_account(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert data["credit_balance_cents"] >= 0, "credit_balance_cents must never be negative"


def assert_standing_order(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in ["ACTIVE", "PAUSED", "CANCELLED"]


def assert_delivery_order(data: dict):
    _assert_mutable_common(data)
    assert data["payment_status"] in ["UNPAID", "PARTIALLY_PAID", "PAID"]
    assert data["fulfillment_status"] in [
        "PENDING", "PACKED", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"]


def assert_delivery_route(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in ["PLANNED", "DISPATCHED", "COMPLETED", "CANCELLED"]


def assert_route_stop(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in ["PENDING", "DELIVERED", "CANCELLED"]


def assert_retail_sale(data: dict):
    """PRD 2.4: RetailSale is immutable — only id and created_at, no updated_at/version."""
    _assert_common(data)
    assert "updated_at" not in data, "RetailSale must not carry updated_at"
    assert "version" not in data, "RetailSale must not carry version"
