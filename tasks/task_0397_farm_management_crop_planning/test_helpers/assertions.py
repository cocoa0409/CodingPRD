"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


# ---------------------------------------------------------------------------
# Common-field assertions (PRD §2.4 — every entity carries these four)
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_parcel(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["acreage"], (int, float)) and data["acreage"] > 0
    assert data["soil_type"] in ("CLAY", "LOAM", "SAND", "SILT")
    assert data["status"] in ("AVAILABLE", "RESTRICTED", "RETIRED")
    assert isinstance(data["active_crop_plan_count"], int)
    assert data["active_crop_plan_count"] >= 0


def assert_crop_plan(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "UNDER_REVISION", "APPROVED", "GROWING", "HARVESTING", "CLOSED", "ABANDONED",
    )
    assert data["crop"] in ("CORN", "SOY", "WHEAT", "COTTON", "ALFALFA")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["planned_acres"] > 0


def assert_input_product(data: dict):
    assert_common_fields(data)
    assert data["category"] in ("SEED", "FERTILIZER", "CHEMICAL")
    assert data["unit"] in ("LB", "GAL", "SEED_UNIT", "TON")
    assert data["unit_cost"] >= 0
    assert isinstance(data["restricted_use"], bool)


def assert_input_lot(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "DEPLETED")
    assert data["quantity_remaining"] >= 0
    assert data["quantity_received"] > 0


def assert_application_record(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("LOGGED", "CONFIRMED", "VOIDED")
    assert data["rate_per_acre"] > 0
    assert data["acres_treated"] > 0


def assert_compliance_record(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert is_valid_uuid(data.get("application_record_id", ""))


def assert_planting_event(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("RECORDED", "VOIDED")
    assert data["acres_planted"] > 0


def assert_harvest_event(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("RECORDED", "VOIDED")
    assert data["acres_harvested"] > 0
    assert 0 <= data["moisture_pct"] <= 100


def assert_harvest_lot(data: dict):
    assert_common_fields(data)
    assert data["quality_status"] in ("UNGRADED", "GRADE_A", "GRADE_B", "REJECTED")
    assert data["sale_status"] in ("IN_INVENTORY", "PARTIALLY_COMMITTED", "FULLY_COMMITTED", "SHIPPED")
    assert data["quantity"] > 0
    assert data["quantity_committed"] >= 0


def assert_sale_contract(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "PARTIALLY_FILLED", "FILLED", "SHIPPED", "CANCELLED")
    assert data["crop"] in ("CORN", "SOY", "WHEAT", "COTTON", "ALFALFA")
    assert data["min_quality"] in ("GRADE_B", "GRADE_A")
    assert data["contracted_quantity"] > 0
    assert data["price_per_unit"] >= 0
    assert data["committed_quantity"] >= 0


def assert_equipment_asset(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "DOWN")
    assert data["kind"] in ("TRACTOR", "COMBINE", "SPRAYER", "PLANTER")
    assert data["hourly_cost"] >= 0


def assert_equipment_usage(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("RECORDED", "VOIDED")


def assert_labor_entry(data: dict):
    assert_common_fields(data)
    assert data["hours"] > 0
    assert data["hourly_rate"] >= 0


def assert_irrigation_event(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert data["inches_applied"] > 0


def assert_applicator(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["certified"], bool)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_money_2dp(value, label="value"):
    """Monetary/quantity figures rounded to exactly 2 decimal places (PRD §2.8)."""
    assert isinstance(value, (int, float)), f"{label} must be a JSON number, got {type(value)}"
    assert_cost_precision(value)
