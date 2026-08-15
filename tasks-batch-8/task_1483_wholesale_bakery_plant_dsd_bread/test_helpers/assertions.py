"""Entity assertions and domain invariant checkers.

Each assert_* validates the fields PRD §2.5 mandates (id/created_at/updated_at/
version) plus the entity-specific shape stated in PRD §3.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert isinstance(data, dict), f"expected object payload, got {type(data)}"
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_plant(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["baseline_flour_index"], (int, float))
    assert isinstance(data["baseline_butter_index"], (int, float))
    assert isinstance(data["day_index"], int) and data["day_index"] >= 0


def assert_product(data: dict):
    _assert_common(data)
    assert data["allergen_class"] in ("NONE", "SESAME", "TREE_NUT", "PEANUT")
    assert isinstance(data["unit_weight_g"], int) and data["unit_weight_g"] > 0
    assert isinstance(data["shelf_life_hours"], int) and data["shelf_life_hours"] > 0
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["flour_share_pct"], (int, float))
    assert isinstance(data["butter_share_pct"], (int, float))
    assert isinstance(data["batch_capacity_units"], int) and data["batch_capacity_units"] > 0
    assert isinstance(data["current_surcharge_cents"], int)


def assert_store(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["lead_time_hours"], int) and data["lead_time_hours"] > 0
    assert isinstance(data["min_remaining_life_hours_on_delivery"], int)
    assert data["min_remaining_life_hours_on_delivery"] >= 0
    assert isinstance(data["shelf_capacity_units"], int) and data["shelf_capacity_units"] > 0
    assert data["stale_credit_tier"] in ("STANDARD", "LIMITED")
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["lifetime_delivered_units"], int)
    assert isinstance(data["lifetime_stale_units"], int)
    assert isinstance(data["stale_ratio"], (int, float))


def assert_driver(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["max_daily_drive_minutes"], int)
    assert isinstance(data["shrink_liability_cents"], int)


def assert_line(data: dict):
    _assert_common(data)
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["hourly_capacity_units"], int) and data["hourly_capacity_units"] > 0
    assert data["cleanliness"] in ("CLEAN", "DIRTY", "SANITIZING")
    assert data["allergen_class_current"] in ("NONE", "SESAME", "TREE_NUT", "PEANUT")


def assert_store_order(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PLACED", "CONFIRMED", "AMENDMENT_PENDING", "LOCKED", "SHORTED",
        "FULFILLED", "PARTIALLY_FULFILLED", "CANCELLED",
    )
    assert isinstance(data["total_units"], int)
    assert isinstance(data["lines"], list)


def assert_production_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "LOCKED", "RELEASED", "RECONCILED", "SUPERSEDED")
    assert isinstance(data["total_planned_units"], int)
    assert isinstance(data["shortfall_units"], int)


def assert_batch(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SCHEDULED", "MIXING", "PROOFING", "BAKING", "COOLING",
        "OVERPROOFED", "RELEASED", "REJECTED", "ABORTED",
    )
    assert isinstance(data["qty_units"], int) and data["qty_units"] > 0


def assert_sanitation_cycle(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "IN_PROGRESS", "VERIFIED", "FAILED")
    assert data["from_allergen_class"] in ("NONE", "SESAME", "TREE_NUT", "PEANUT")
    assert data["to_allergen_class"] in ("NONE", "SESAME", "TREE_NUT", "PEANUT")
    assert isinstance(data["required_minutes"], int) and data["required_minutes"] >= 0


def assert_route(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PLANNED", "LOADING", "DISPATCHED", "COMPLETED", "SETTLED", "CANCELLED",
    )
    assert isinstance(data["truck_capacity_units"], int) and data["truck_capacity_units"] > 0
    assert isinstance(data["loaded_units"], int)
    assert isinstance(data["delivered_units"], int)
    assert isinstance(data["refused_units"], int)


def assert_route_stop(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "DELIVERED", "SKIPPED", "RECONCILED")
    assert isinstance(data["planned_units"], int)
    assert isinstance(data["batch_ids"], list)
    assert isinstance(data["shortfall_flag"], bool)


def assert_stale_return(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING_VERIFICATION", "VERIFIED", "DISPUTED", "CREDITED", "REVERSED", "REJECTED",
    )
    assert isinstance(data["provisional_credit_cents"], int)
    assert isinstance(data["dispute_round"], int) and data["dispute_round"] >= 0


def assert_thrift_sale(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECORDED", "VOIDED")
    assert isinstance(data["units"], int) and data["units"] > 0
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_ingredient_index(data: dict):
    _assert_common(data)
    assert data["ingredient"] in ("FLOUR", "BUTTER")
    assert data["status"] in ("FORECAST", "PUBLISHED")
    assert isinstance(data["forecast_value"], (int, float))


def assert_surcharge_schedule(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROVISIONAL", "FINALIZED")
    assert isinstance(data["provisional_surcharge_cents"], int)
