"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields carried by every entity except WasteRecord (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["share_basis"] in ("GROSS", "NET")
    assert data["spoilage_valuation"] in ("FIFO", "WEIGHTED_AVG")
    assert 0 <= data["venue_share_pct"] <= 100
    assert 0 <= data["service_fee_pct"] <= 100


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["venue_id"], str)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["perishable"], bool)


def assert_event(data: dict):
    _assert_common(data)
    assert isinstance(data["venue_id"], str)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("SCHEDULED", "DOORS_OPEN", "IN_PROGRESS", "SETTLED")
    assert isinstance(data["peak_window"], bool)
    assert isinstance(data["event_multiplier_pct"], int)
    assert isinstance(data["gross_sales_cents"], int)
    assert isinstance(data["waste_cost_cents"], int)


def assert_stand(data: dict):
    _assert_common(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["demand_tier"] in ("LOW", "MID", "HIGH")
    assert data["status"] in ("CLOSED", "OPEN", "SUSPENDED")
    assert isinstance(data["expected_orders_per_hour"], int)
    assert isinstance(data["required_staff"], int)
    assert isinstance(data["assigned_staff_count"], int)


def assert_menu_item(data: dict):
    _assert_common(data)
    assert isinstance(data["stand_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["available"], bool)
    assert isinstance(data["price_cents"], int)


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["stand_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["received_qty"], int)
    assert isinstance(data["remaining_qty"], int)
    assert isinstance(data["unit_cost_cents"], int)
    assert data["status"] in ("ACTIVE", "DEPLETED", "EXPIRED")


def assert_replenishment(data: dict):
    _assert_common(data)
    assert isinstance(data["stand_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["requested_qty"], int)
    assert isinstance(data["fulfilled_qty"], int)
    assert data["status"] in ("REQUESTED", "PICKING", "DELIVERED", "CANCELLED")


def assert_transfer(data: dict):
    _assert_common(data)
    assert isinstance(data["from_stand_id"], str)
    assert isinstance(data["to_stand_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["qty"], int)
    assert data["status"] in ("DRAFT", "IN_TRANSIT", "COMPLETED", "CANCELLED")


def assert_order(data: dict):
    _assert_common(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["stand_id"], str)
    assert isinstance(data["patron_id"], str)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["service_fee_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in ("CART", "PLACED", "READY", "PICKED_UP", "CANCELLED")


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["menu_item_id"], str)
    assert isinstance(data["qty"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_subtotal_cents"], int)
    assert isinstance(data["line_fee_cents"], int)


def assert_staff_shift(data: dict):
    _assert_common(data)
    assert isinstance(data["stand_id"], str)
    assert isinstance(data["worker_name"], str) and len(data["worker_name"]) > 0
    assert data["status"] in ("SCHEDULED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED")


def assert_patron(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["wallet_credit_cents"], int)


def assert_revenue_share_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["gross_sales_cents"], int)
    assert isinstance(data["waste_cost_cents"], int)
    assert isinstance(data["venue_share_cents"], int)
    assert isinstance(data["operator_net_cents"], int)


def assert_waste_record(data: dict):
    """WasteRecord is immutable (PRD §2.4): id + created_at only, NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["stand_id"], str)
    assert isinstance(data["product_id"], str)
    assert data["reason"] in ("EXPIRY", "SPILLAGE", "DAMAGE")
    assert isinstance(data["qty"], int)
    assert isinstance(data["cost_cents"], int)


def assert_no_version_field(data: dict):
    """For immutable entities (PRD §2.4): assert version/updated_at are absent."""
    assert "version" not in data, "immutable WasteRecord must not expose a version field"
    assert "updated_at" not in data, "immutable WasteRecord must not expose an updated_at field"
