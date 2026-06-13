"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (for non-Sale entities)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_host_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["contact_email"], str)
    assert data["commission_model"] in ("FLAT", "TIERED")
    assert isinstance(data["flat_commission_pct"], (int, float))
    assert isinstance(data["monthly_guarantee_cents"], int)
    assert isinstance(data["lifetime_commission_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str)
    assert data["category"] in ("BEVERAGE", "SNACK", "FRESH_FOOD")
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["shelf_life_days"], int)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_machine(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["host_site_id"], str)
    assert isinstance(data["asset_tag"], str)
    assert data["machine_type"] in ("SNACK_VENDOR", "BEVERAGE_VENDOR", "MICRO_MARKET_KIOSK")
    assert isinstance(data["cash_capacity_cents"], int)
    assert isinstance(data["cash_on_hand_cents"], int)
    assert data["stock_status"] in ("STOCKED", "LOW_STOCK", "STOCKOUT")
    assert data["cash_status"] in ("CASH_OK", "CASH_FULL_WARN")
    assert data["service_status"] in ("IN_SERVICE", "FROZEN")


def assert_slot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["slot_code"], str)
    assert isinstance(data["capacity"], int)
    assert isinstance(data["par_level"], int)
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["on_hand"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["slot_id"], str)
    assert isinstance(data["filled_units"], int)
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["remaining_units"], int)
    assert data["status"] in ("AVAILABLE", "DEPLETED", "SPOILED")


def assert_driver(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["employee_code"], str)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["driver_id"], str)
    assert data["status"] in ("DRAFT", "DISPATCHED", "CLOSED")


def assert_route_stop(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["route_id"], str)
    assert isinstance(data["machine_id"], str)
    assert isinstance(data["window_start_min"], int)
    assert isinstance(data["window_end_min"], int)
    assert data["status"] in ("PLANNED", "KITTED", "VISITED", "SKIPPED")


def assert_visit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["route_stop_id"], str)
    assert isinstance(data["machine_id"], str)
    assert data["status"] in ("DRAFT", "RECONCILED", "REJECTED")


def assert_statement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["host_site_id"], str)
    assert isinstance(data["gross_sales_cents"], int)
    assert isinstance(data["shrink_chargeback_cents"], int)
    assert isinstance(data["gross_commission_cents"], int)
    assert isinstance(data["net_commission_cents"], int)
    assert data["status"] in ("OPEN", "FINALIZED")


def assert_ticket(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["machine_id"], str)
    assert data["issue_type"] in ("JAM", "TELEMETRY_ALERT", "VANDALISM", "COIN_MECH")
    assert isinstance(data["blocking"], bool)
    assert data["status"] in ("OPEN", "IN_PROGRESS", "RESOLVED", "REOPENED")


def assert_sale(data: dict):
    """A Sale is an immutable event: id + created_at only (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["machine_id"], str)
    assert isinstance(data["slot_id"], str)
    assert isinstance(data["quantity"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["gross_cents"], int)
    assert data["payment_method"] in ("CASHLESS", "CASH")
    assert data["settlement_status"] in ("SETTLED", "VOID")


def assert_sale_immutable_shape(data: dict):
    """A Sale carries neither updated_at nor version (PRD Section 2.4)."""
    assert "version" not in data, "Sale must not expose a version field"
    assert "updated_at" not in data, "Sale must not expose an updated_at field"
