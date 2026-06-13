"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id, created_at, updated_at, version are present and well-formed for every resource."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_distributor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["catalog_revision"], int)
    assert data["catalog_revision"] >= 0


def assert_warehouse(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["distributor_id"])
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str)


def assert_route(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["distributor_id"])
    assert is_valid_uuid(data["warehouse_id"])
    assert 0 <= data["delivery_dow"] <= 6
    assert data["cutoff_lead_hours"] >= 0
    assert data["min_delivery_gap_days"] >= 0


def assert_product(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["distributor_id"])
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["splits_per_case"] >= 1
    assert isinstance(data["split_allowed"], bool)
    assert isinstance(data["perishable"], bool)
    assert data["case_cost_cents"] >= 0
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_price_tier(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert data["min_cases"] >= 1
    assert data["case_price_cents"] >= 0


def assert_customer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["distributor_id"])
    assert is_valid_uuid(data["route_id"])
    assert data["credit_limit_cents"] >= 0
    assert data["split_fee_cents"] >= 0
    assert isinstance(data["ar_balance_cents"], int)
    assert data["ar_status"] in ("ACTIVE", "CREDIT_HOLD", "CLOSED")


def assert_order_guide(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["distributor_id"])


def assert_order_guide_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_guide_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["par_level_splits"] >= 0
    assert data["on_hand_splits"] >= 0


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["warehouse_id"])
    assert data["on_hand_splits"] >= 0
    assert data["reserved_splits"] >= 0


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["distributor_id"])
    assert data["fulfillment_status"] in (
        "DRAFT", "SUBMITTED", "PICKING", "LOADED", "DELIVERED", "CANCELLED",
    )
    assert data["credit_status"] in ("PENDING", "APPROVED", "ON_HOLD")
    assert isinstance(data["settled"], bool)
    assert isinstance(data["goods_subtotal_cents"], int)
    assert isinstance(data["split_fee_total_cents"], int)
    assert isinstance(data["order_total_cents"], int)


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["uom"] in ("CASE", "SPLIT")
    assert data["ordered_qty"] >= 1
    assert data["line_status"] in ("OPEN", "ALLOCATED", "SHORTED", "REMOVED")
    assert isinstance(data["substituted"], bool)


def assert_shipment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["warehouse_id"])
    assert data["status"] in ("PICKING", "LOADED", "DELIVERED")


def assert_return(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["order_line_id"])
    assert data["reason"] in ("DAMAGED", "OVERAGE", "QUALITY", "WRONG_ITEM")
    assert data["return_splits"] >= 1
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "CREDITED")
