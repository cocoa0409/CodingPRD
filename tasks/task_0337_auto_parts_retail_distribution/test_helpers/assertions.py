"""Entity assertions and domain invariant checkers.

Each assert_{entity}() verifies the shape and field types the PRD promises. The
invariant checkers encode cross-field rules that must always hold (inventory never
negative, available = on_hand - reserved, A/R never negative).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system-managed fields for mutable entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_immutable_common(data: dict):
    """Immutable association records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable record must not carry a version field"
    assert "updated_at" not in data, "immutable record must not carry an updated_at field"


def assert_part(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["description"], str)
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["cost_cents"], int)
    assert isinstance(data["core_charge_cents"], int)
    assert isinstance(data["is_rebuildable"], bool)
    assert isinstance(data["warranty_days"], int)
    assert isinstance(data["stockable"], bool)
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["reserved_qty"], int)
    assert isinstance(data["available_qty"], int)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert_part_inventory_invariants(data)


def assert_part_inventory_invariants(data: dict):
    """Inventory accounting invariants (PRD §2.6)."""
    assert data["on_hand_qty"] >= 0, "on_hand_qty must never be negative"
    assert data["reserved_qty"] >= 0, "reserved_qty must never be negative"
    assert data["available_qty"] >= 0, "available_qty must never be negative"
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], (
        "available_qty must equal on_hand_qty - reserved_qty"
    )


def assert_vehicle(data: dict):
    _assert_common(data)
    assert isinstance(data["year"], int)
    assert isinstance(data["make"], str)
    assert isinstance(data["model"], str)
    assert isinstance(data["engine"], str)


def assert_fitment(data: dict):
    _assert_immutable_common(data)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["vehicle_id"], str)
    assert data["position"] in ("FRONT", "REAR", "LEFT", "RIGHT", "UNIVERSAL")
    assert isinstance(data["notes"], str)


def assert_cross_reference(data: dict):
    _assert_immutable_common(data)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["interchange_part_id"], str)
    assert data["relation"] in ("SUPERSEDES", "EQUIVALENT", "OE_TO_AFTERMARKET")


def assert_price_tier(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["discount_pct"], (int, float))
    assert isinstance(data["core_discount_pct"], (int, float))
    assert isinstance(data["min_margin_pct"], (int, float))


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["account_type"] in ("RETAIL", "WHOLESALE")
    assert isinstance(data["price_tier_id"], str)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["ar_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "ON_HOLD")
    assert data["ar_balance_cents"] >= 0, "ar_balance_cents must never be negative"


def assert_sales_order(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert data["channel"] in ("COUNTER", "WHOLESALE")
    assert data["fulfillment_status"] in ("OPEN", "ALLOCATED", "SHIPPED", "CANCELLED")
    assert data["settlement_status"] in ("UNBILLED", "INVOICED", "PAID")
    assert isinstance(data["merchandise_subtotal_cents"], int)
    assert isinstance(data["core_subtotal_cents"], int)
    assert isinstance(data["order_total_cents"], int)
    assert isinstance(data["hotshot_fee_cents"], int)
    assert data["order_total_cents"] == (
        data["merchandise_subtotal_cents"] + data["core_subtotal_cents"]
        + data["hotshot_fee_cents"]
    ), "order_total_cents must equal merch + core + hotshot subtotals"


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["price_tier_id"], str)
    assert isinstance(data["qty"], int)
    assert isinstance(data["is_special_order"], bool)
    assert isinstance(data["unit_merch_price_cents"], int)
    assert isinstance(data["unit_core_price_cents"], int)
    assert isinstance(data["line_merch_total_cents"], int)
    assert isinstance(data["line_core_total_cents"], int)
    assert isinstance(data["cores_outstanding"], int)
    assert data["status"] in ("PENDING", "ALLOCATED", "SHIPPED", "CANCELLED")


def assert_core_return(data: dict):
    _assert_common(data)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["qty"], int)
    assert isinstance(data["refund_cents"], int)
    assert data["status"] in ("PENDING_INSPECTION", "ACCEPTED", "REJECTED")


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["qty"], int)
    assert isinstance(data["reason"], str)
    assert data["resolution"] in ("REPLACE", "REFUND")
    assert isinstance(data["credit_cents"], int)
    assert isinstance(data["restock_defective"], bool)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED")


def assert_reorder_request(data: dict):
    _assert_common(data)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["qty_ordered"], int)
    assert isinstance(data["qty_received"], int)
    assert data["status"] in (
        "SUGGESTED", "ORDERED", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED"
    )
    assert data["qty_received"] <= data["qty_ordered"], "qty_received must not exceed qty_ordered"


def assert_driver(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["turnaround_min"], int)


def assert_bay(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str)


def assert_delivery_run(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["driver_id"], str)
    assert isinstance(data["bay_id"], str)
    assert isinstance(data["window_start_min"], int)
    assert isinstance(data["window_end_min"], int)
    assert data["window_end_min"] > data["window_start_min"]
    assert data["status"] in ("SCHEDULED", "DISPATCHED", "DELIVERED", "CANCELLED")
