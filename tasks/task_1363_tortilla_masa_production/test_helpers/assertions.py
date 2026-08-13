"""Entity assertions and domain invariant checkers (PRD §2.4, §2.10)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_ingredient_lot(data: dict):
    _assert_common(data)
    assert data["lot_status"] in ["RECEIVED", "CONDITIONED", "DEPLETED", "REJECTED"]
    assert data["corn_variety"] in ["WHITE_CORN", "YELLOW_CORN", "BLUE_CORN"]
    assert data["received_kg"] > 0
    assert data["available_kg"] >= 0, "available_kg is never negative (PRD §3.1)"


def assert_nixtamal_batch(data: dict):
    _assert_common(data)
    assert data["batch_status"] in [
        "PLANNED", "COOKING", "STEEPING", "MILLING",
        "MASA_AVAILABLE", "QUARANTINED", "DEPLETED", "REJECTED",
    ]
    assert data["corn_kg"] > 0
    assert isinstance(data["recook_count"], int)


def assert_product(data: dict):
    _assert_common(data)
    assert data["diameter_in"] in ["D6", "D8", "D10", "D12"]
    assert data["channel"] in ["RETAIL", "FOODSERVICE"]
    assert data["preservative_system"] in ["NONE", "PROPIONATE", "FUMARIC_ACID"]
    assert data["allergen_class"] in ["CORN_ONLY", "WHEAT_FLOUR", "SOY_BLENDED"]
    assert data["product_status"] in ["ACTIVE", "DISCONTINUED"]
    assert data["count_per_pack"] > 0 and data["packs_per_case"] > 0


def assert_production_line(data: dict):
    _assert_common(data)
    assert data["allergen_zone"] in ["DEDICATED_CORN", "SHARED"]
    assert data["line_status"] in ["ACTIVE", "DOWN"]
    assert data["line_posture"] in ["AVAILABLE", "RUNNING", "CHANGEOVER_PENDING"]
    assert data["cases_per_hour"] > 0


def assert_production_run(data: dict):
    _assert_common(data)
    assert data["production_status"] in [
        "PLANNED", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED",
    ]
    assert data["qc_status"] in ["PENDING", "ON_HOLD", "PASSED"]
    assert data["planned_cases"] > 0


def assert_batch_allocation(data: dict):
    _assert_common(data)
    assert data["allocation_status"] in ["RESERVED", "CONSUMED", "RELEASED"]
    assert data["allocated_kg"] > 0


def assert_changeover_record(data: dict):
    _assert_common(data)
    assert data["changeover_status"] in [
        "REQUIRED", "IN_PROGRESS", "VERIFIED", "FAILED", "CANCELLED",
    ]
    assert data["required_level"] in ["FLUSH", "WET_WASH", "FULL_SANITATION"]
    assert isinstance(data["fail_count"], int)


def assert_pack_order(data: dict):
    _assert_common(data)
    assert data["pack_status"] in [
        "OPEN", "PACKING", "PASSED", "HOLD", "SEALED", "REJECTED", "CANCELLED",
    ]
    assert data["verification_method"] in ["AVERAGE_WEIGHT", "COUNT_VERIFY"]
    assert data["cases_planned"] > 0


def assert_customer_account(data: dict):
    _assert_common(data)
    assert data["channel"] in ["RETAIL_GROCERY", "TORTILLERIA", "FOODSERVICE_DIST"]
    assert data["priority_tier"] in ["A", "B", "C"]
    assert data["credit_standing"] in ["GOOD", "HOLD"]
    assert data["base_weekly_cases"] >= 0
    assert 1 <= data["min_shelf_life_pct"] <= 100


def assert_seasonal_window(data: dict):
    _assert_common(data)
    assert data["window_status"] in ["SCHEDULED", "ACTIVE", "CLOSED"]
    assert data["demand_multiplier"] >= 1.0
    assert isinstance(data["is_strict"], bool)


def assert_seasonal_allotment(data: dict):
    _assert_common(data)
    assert data["allotment_status"] in ["ACTIVE", "CLOSED"]
    assert data["allotted_cases"] >= 0
    assert data["consumed_cases"] >= 0
    assert data["remaining_cases"] == data["allotted_cases"] - data["consumed_cases"]


def assert_route(data: dict):
    _assert_common(data)
    assert data["route_status"] in ["PLANNED", "DISPATCHED", "COMPLETED", "CANCELLED"]
    assert data["vehicle_capacity_cases"] > 0
    assert data["open_cases"] == data["vehicle_capacity_cases"] - data["committed_cases"]


def assert_route_stop(data: dict):
    _assert_common(data)
    assert data["stop_status"] in ["ALLOCATED", "DELIVERED", "SHORTED"]
    assert data["requested_cases"] > 0


def assert_masa_conservation(batch: dict, active_allocated_kg: float):
    """PRD §2.10: actual_masa_kg == masa_available_kg + RESERVED/CONSUMED sum."""
    lhs = round(float(batch["actual_masa_kg"]), 2)
    rhs = round(float(batch["masa_available_kg"]) + active_allocated_kg, 2)
    assert abs(lhs - rhs) < 1e-6, (
        f"masa conservation violated: actual {lhs} != available "
        f"{batch['masa_available_kg']} + active {active_allocated_kg}"
    )


def assert_case_load(pack: dict, active_allocated_cases: int):
    """PRD §2.10: cases_packed == cases_available + ALLOCATED/DELIVERED sum."""
    assert pack["cases_packed"] == pack["cases_available"] + active_allocated_cases, (
        f"case load violated: packed {pack['cases_packed']} != available "
        f"{pack['cases_available']} + active {active_allocated_cases}"
    )
