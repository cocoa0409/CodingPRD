"""Entity assertions and domain invariant checkers (Ghost Kitchen Platform)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system-managed fields for versioned entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_stall(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str)
    assert isinstance(data["open_minute_of_day"], int)
    assert isinstance(data["close_minute_of_day"], int)
    assert 0 <= data["open_minute_of_day"] < data["close_minute_of_day"] <= 1440
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["equipment_count"], int) and data["equipment_count"] >= 0


def assert_brand(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["owner_email"], str)
    assert isinstance(data["commission_rate_bps"], int)
    assert 0 <= data["commission_rate_bps"] <= 5000
    assert data["status"] in ("ONBOARDING", "ACTIVE", "DEACTIVATED")
    assert data["availability"] in ("LISTED", "PAUSED")
    assert isinstance(data["ledger_balance_cents"], int)


def assert_lease(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["stall_id"])
    assert is_valid_uuid(data["brand_id"])
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] > 0
    assert isinstance(data["priority_rank"], int) and data["priority_rank"] >= 1
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")


def assert_equipment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["stall_id"])
    assert data["equipment_type"] in ("FRYER", "OVEN", "GRILL", "PREP_STATION")
    assert isinstance(data["turnaround_buffer_minutes"], int) and data["turnaround_buffer_minutes"] >= 0
    assert data["status"] in ("AVAILABLE", "MAINTENANCE", "RETIRED")


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["equipment_id"])
    assert isinstance(data["start_minute"], int) and data["start_minute"] >= 0
    assert isinstance(data["end_minute"], int) and data["end_minute"] > data["start_minute"]
    assert data["status"] in ("HELD", "RELEASED")


def assert_menu_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["brand_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert isinstance(data["prep_minutes"], int) and data["prep_minutes"] >= 1
    assert data["required_equipment_type"] in ("FRYER", "OVEN", "GRILL", "PREP_STATION")
    assert data["availability"] in ("AVAILABLE", "SOLD_OUT")


def assert_recipe_component(data: dict):
    """RecipeComponent is immutable: id + created_at only; NO updated_at, NO version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["menu_item_id"])
    assert isinstance(data["ingredient_name"], str) and len(data["ingredient_name"]) > 0
    assert isinstance(data["quantity_grams"], int) and data["quantity_grams"] > 0


def assert_ingredient_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["stall_id"])
    assert isinstance(data["ingredient_name"], str) and len(data["ingredient_name"]) > 0
    assert isinstance(data["unit_cost_cents_per_gram"], int) and data["unit_cost_cents_per_gram"] >= 0
    assert isinstance(data["grams_received"], int) and data["grams_received"] > 0
    assert isinstance(data["grams_remaining"], int) and data["grams_remaining"] >= 0


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["brand_id"])
    assert data["aggregator"] in ("DOORDASH", "UBER_EATS")
    assert isinstance(data["external_ref"], str)
    assert isinstance(data["line_items"], list)
    assert isinstance(data["gross_revenue_cents"], int) and data["gross_revenue_cents"] >= 0
    assert isinstance(data["commission_cents"], int) and data["commission_cents"] >= 0
    assert isinstance(data["food_cost_cents"], int) and data["food_cost_cents"] >= 0
    assert data["status"] in ("INGESTED", "ROUTED", "PREPARING", "FULFILLED", "CANCELLED", "REJECTED")
