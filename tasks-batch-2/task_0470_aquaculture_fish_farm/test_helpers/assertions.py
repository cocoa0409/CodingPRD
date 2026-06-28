"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape and field types declared for the
entity in the PRD; append-only records (StockingEvent, FeedLog,
WaterQualityReading) are asserted WITHOUT updated_at / version because the PRD
states those fields are absent for them.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "version" not in data, \
        "append-only record must not carry a version field"
    assert "updated_at" not in data, \
        "append-only record must not carry an updated_at field"


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------
def assert_species(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["common_name"], str) and data["common_name"]
    assert isinstance(data["code"], str) and data["code"]
    assert data["target_market_weight_g"] > 0
    assert data["base_daily_growth_g"] > 0
    assert 0 < data["default_processing_yield_pct"] <= 1
    assert data["max_water_temp_c"] > data["min_water_temp_c"]


def assert_tank(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["kind"] in ["TANK", "POND", "RACEWAY", "CAGE"]
    assert data["volume_liters"] > 0
    assert data["max_biomass_kg"] > 0
    assert data["posture"] in ["OPEN", "RESTRICTED", "FROZEN"]
    assert data["posture_override"] in [None, "RESTRICTED", "FROZEN"]
    assert data["current_biomass_kg"] >= 0


def assert_broodstock_batch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["species_id"])
    assert data["fingerling_count"] >= 0
    assert data["allocated_count"] >= 0
    assert data["status"] in ["AVAILABLE", "DEPLETED"]


def assert_cohort(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str) and data["label"]
    assert is_valid_uuid(data["species_id"])
    assert is_valid_uuid(data["current_tank_id"])
    assert data["fish_count"] >= 0
    assert data["stocked_avg_weight_g"] > 0
    assert data["cumulative_feed_kg"] >= 0
    assert data["estimated_biomass_kg"] >= 0
    assert data["lifecycle_status"] in [
        "STOCKED", "GROWING", "HARVESTING", "HARVESTED",
    ]
    assert data["health_status"] in ["HEALTHY", "UNDER_TREATMENT", "WITHDRAWAL"]
    assert data["operational_status"] in ["ACTIVE", "SUSPENDED"]


def assert_grading_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["source_cohort_id"])
    assert isinstance(data["planned_splits"], list)
    assert data["status"] in ["DRAFT", "PLANNED", "COMMITTED", "CANCELLED"]
    assert isinstance(data["child_cohort_ids"], list)


def assert_health_treatment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["cohort_id"])
    assert is_valid_uuid(data["tank_id"])
    assert isinstance(data["medication"], str) and data["medication"]
    assert data["duration_days"] > 0
    assert data["withdrawal_days"] >= 0
    assert is_iso8601_timestamp(data["treatment_end_at"])
    assert is_iso8601_timestamp(data["withdrawal_end_at"])
    assert data["status"] in ["ACTIVE", "COMPLETED", "CLEARED"]


def assert_harvest_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["cohort_id"])
    assert data["planned_fish_count"] > 0
    assert data["status"] in [
        "DRAFT", "SCHEDULED", "BLOCKED", "IN_PROGRESS", "COMPLETED", "CANCELLED",
    ]


def assert_processing_batch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["harvest_order_id"])
    assert data["input_live_weight_kg"] >= 0
    assert data["estimated_yield_kg"] >= 0
    assert data["status"] in ["DRAFT", "PROCESSING", "COMPLETED", "REJECTED"]


def assert_product_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["processing_batch_id"])
    assert is_valid_uuid(data["species_id"])
    assert data["total_weight_kg"] >= 0
    assert data["reserved_weight_kg"] >= 0
    assert data["available_weight_kg"] >= 0
    assert data["shipped_weight_kg"] >= 0
    assert data["price_per_kg"] > 0
    assert data["status"] in ["AVAILABLE", "DEPLETED"]
    assert_lot_weight_conservation(data)


def assert_sales_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert data["discount_tier"] in ["NONE", "BRONZE", "SILVER", "GOLD"]
    assert data["order_total"] >= 0
    assert data["status"] in ["DRAFT", "CONFIRMED", "FULFILLED", "CANCELLED"]


def assert_sales_order_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sales_order_id"])
    assert is_valid_uuid(data["product_lot_id"])
    assert data["weight_kg"] > 0
    assert data["line_subtotal"] >= 0


def assert_stocking_event(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["cohort_id"])
    assert is_valid_uuid(data["tank_id"])
    assert data["fish_count"] > 0


def assert_feed_log(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["cohort_id"])
    assert data["amount_kg"] > 0
    assert isinstance(data["feed_type"], str)


def assert_water_quality_reading(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["tank_id"])
    assert data["dissolved_oxygen_mg_l"] >= 0
    assert data["ammonia_mg_l"] >= 0
    assert data["severity"] in ["NORMAL", "WARNING", "CRITICAL"]


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_lot_weight_conservation(lot: dict):
    """Conservation invariant (§2.10): total == available + reserved + shipped."""
    total = lot["total_weight_kg"]
    parts = (
        lot["available_weight_kg"]
        + lot["reserved_weight_kg"]
        + lot["shipped_weight_kg"]
    )
    assert abs(total - parts) < 0.01, (
        f"weight conservation broken: total={total} != "
        f"available+reserved+shipped={parts}"
    )
    assert_cost_precision(lot["total_weight_kg"])
    assert_cost_precision(lot["available_weight_kg"])
    assert_cost_precision(lot["reserved_weight_kg"])
    assert_cost_precision(lot["shipped_weight_kg"])
