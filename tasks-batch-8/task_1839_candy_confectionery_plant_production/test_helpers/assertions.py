"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime for comparison."""
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"Not a valid ISO 8601 UTC timestamp: {value!r}")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')!r}")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku_code"], str) and data["sku_code"]
    assert isinstance(data["name"], str)
    assert data["product_type"] in ("STANDARD", "SEASONAL", "GIFT_SET")
    assert data["brand"] in ("OWN", "PRIVATE_LABEL")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert data["unit_weight_grams"] > 0
    assert isinstance(data["shelf_life_days"], int) and data["shelf_life_days"] > 0
    assert isinstance(data["packaging_component_id"], str)


def assert_recipe(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["shape_code"], str) and data["shape_code"]
    assert data["cook_temp_min_c"] <= data["cook_temp_max_c"]
    assert data["temper_exit_min_c"] <= data["temper_exit_max_c"]
    assert isinstance(data["allergens"], list)
    assert 0 < data["standard_yield_pct"] <= 1


def assert_packaging_component(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku_code"], str) and data["sku_code"]
    assert isinstance(data["units_per_component"], int) and data["units_per_component"] >= 1
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    assert isinstance(data["qty_on_hand"], int) and data["qty_on_hand"] >= 0
    assert isinstance(data["qty_reserved"], int) and data["qty_reserved"] >= 0
    assert isinstance(data["qty_available"], int)
    assert_packaging_invariants(data)


def assert_packaging_invariants(data: dict):
    """The packaging ledger invariant that must hold at all times."""
    assert data["qty_available"] == data["qty_on_hand"] - data["qty_reserved"], (
        "qty_available must equal qty_on_hand - qty_reserved")
    assert data["qty_available"] >= 0, "qty_available must never drop below zero"


def assert_packaging_po(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["component_id"], str)
    assert isinstance(data["order_qty"], int) and data["order_qty"] > 0
    assert is_iso8601_timestamp(data["ordered_at"])
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in ("ORDERED", "RECEIVED")
    if data["status"] == "RECEIVED":
        assert data["received_at"] is not None


def assert_mold(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["shape_code"], str) and data["shape_code"]
    assert isinstance(data["cavity_count"], int) and data["cavity_count"] > 0
    assert data["status"] in ("AVAILABLE", "INSTALLED")


def assert_production_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert "current_mold_id" in data
    assert isinstance(data["cleared_allergens"], list)
    assert data["status"] in ("AVAILABLE", "CHANGEOVER")


def assert_changeover(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["line_id"], str)
    assert data["changeover_type"] in ("SHAPE_ONLY", "FULL", "ALLERGEN_WASH")
    assert data["status"] in ("PENDING_SWAB", "PENDING_QA", "RELEASED")


def assert_seasonal_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["season_code"], str) and data["season_code"]
    assert isinstance(data["target_units"], int) and data["target_units"] > 0
    assert isinstance(data["markdown_tiers"], list)
    assert isinstance(data["confirmed_build_units"], int)
    assert isinstance(data["projected_build_units"], int)
    assert isinstance(data["coverage_pct"], (int, float))
    assert isinstance(data["shortfall"], bool)
    assert data["status"] in ("DRAFT", "PUBLISHED", "CLOSED")
    assert_window_projection_invariants(data)


def assert_window_projection_invariants(data: dict):
    """Projection invariants: projected >= confirmed; shortfall flag consistent."""
    assert data["projected_build_units"] >= data["confirmed_build_units"], (
        "the projected figure is at least the confirmed one")
    assert data["shortfall"] == (
        data["confirmed_build_units"] < data["target_units"])


def assert_production_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["window_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["recipe_id"], str)
    assert isinstance(data["line_id"], str)
    assert data["run_type"] in ("STANDARD", "GIFT_ASSEMBLY", "REWORK")
    assert isinstance(data["planned_units"], int) and data["planned_units"] > 0
    assert isinstance(data["packaging_reserved_qty"], int)
    assert data["status"] in (
        "PLANNED", "IN_PROGRESS", "ON_HOLD", "COMPLETED", "CANCELLED")


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["run_id"], str)
    assert is_iso8601_timestamp(data["mfg_date"])
    assert is_iso8601_timestamp(data["expiry_date"])
    assert isinstance(data["qty_on_hand"], int) and data["qty_on_hand"] >= 0
    assert isinstance(data["qty_reserved_rework"], int)
    assert isinstance(data["qty_scrapped"], int) and data["qty_scrapped"] >= 0
    assert isinstance(data["unit_price_cents"], int)
    assert data["quality_status"] in ("OK", "SUSPECT")
    assert data["status"] in ("ACTIVE", "BLOCKED", "DEPLETED", "SCRAPPED")


def assert_quality_hold(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lot_id"], str)
    assert data["defect_type"] in (
        "BLOOM", "TEMPER_DEVIATION", "FOREIGN_MATERIAL", "OTHER")
    assert isinstance(data["affected_units"], int) and data["affected_units"] > 0
    assert isinstance(data["lot_qty_at_open"], int)
    assert isinstance(data["defect_rate_pct"], (int, float))
    assert isinstance(data["opened_by"], str) and data["opened_by"]
    assert data["status"] in (
        "OPEN", "RELEASED", "SCRAPPED", "REWORK_PENDING", "CLOSED_REWORK")


def assert_gift_component(data: dict):
    """Gift-set bill-of-material rows are immutable: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')!r}")
    assert "updated_at" not in data, "gift-component rows carry no updated_at"
    assert "version" not in data, "gift-component rows carry no version"
    assert isinstance(data["gift_product_id"], str)
    assert isinstance(data["component_product_id"], str)
    assert isinstance(data["qty_per_set"], int) and data["qty_per_set"] > 0
