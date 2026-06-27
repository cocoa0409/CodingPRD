"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def _assert_common(data: dict):
    """id + timestamps + version for standard (non-append-only) resources."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def assert_herd(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["federal_order_number"], str)
    assert data["milk_quality_status"] in ("GOOD", "WARNING", "PENALIZED")
    assert isinstance(data["active_animal_count"], int) and data["active_animal_count"] >= 0


def assert_parlor(data: dict):
    _assert_common(data)
    assert isinstance(data["herd_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["stall_capacity"], int) and data["stall_capacity"] >= 1
    assert isinstance(data["turnaround_minutes"], int) and data["turnaround_minutes"] >= 0


def assert_ration(data: dict):
    _assert_common(data)
    assert isinstance(data["herd_id"], str)
    assert isinstance(data["ingredients"], list)
    assert isinstance(data["daily_feed_cost_per_cow"], (int, float))
    assert_cost_precision(data["daily_feed_cost_per_cow"])
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_price_sheet(data: dict):
    _assert_common(data)
    assert isinstance(data["herd_id"], str)
    assert isinstance(data["settlement_month"], str)
    for f in ("fat_price_per_lb", "protein_price_per_lb", "other_solids_price_per_lb",
              "ppd_per_cwt", "advance_rate_per_cwt", "hauling_rate_per_cwt"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_animal(data: dict):
    _assert_common(data)
    assert isinstance(data["herd_id"], str)
    assert isinstance(data["ear_tag"], str)
    assert isinstance(data["parity"], int) and data["parity"] >= 0
    assert data["status"] in ("HEIFER", "ACTIVE", "DRY", "SOLD", "CULLED", "DIED")
    assert isinstance(data["milk_eligible"], bool)


def assert_lactation(data: dict):
    _assert_common(data)
    assert isinstance(data["animal_id"], str)
    assert isinstance(data["herd_id"], str)
    assert isinstance(data["parity"], int)
    assert isinstance(data["cumulative_milk_lbs"], (int, float))
    assert isinstance(data["projected_305d_milk_lbs"], (int, float))
    assert data["status"] in ("OPEN", "DRY", "CLOSED")


def assert_test_day_record(data: dict):
    # Append-only: id + created_at only, no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "TestDayRecord is append-only: no updated_at"
    assert "version" not in data, "TestDayRecord is append-only: no version"
    assert isinstance(data["lactation_id"], str)
    assert isinstance(data["day_in_milk"], int) and data["day_in_milk"] >= 1
    assert isinstance(data["milk_weight_lbs"], (int, float)) and data["milk_weight_lbs"] >= 0


def assert_milking_shift(data: dict):
    _assert_common(data)
    assert isinstance(data["parlor_id"], str)
    assert isinstance(data["herd_id"], str)
    assert data["status"] in ("LOGGED", "VOIDED")
    assert isinstance(data["cows_milked"], int) and data["cows_milked"] >= 0


def assert_breeding_event(data: dict):
    _assert_common(data)
    assert isinstance(data["animal_id"], str)
    assert isinstance(data["herd_id"], str)
    assert data["status"] in ("BRED", "CONFIRMED_PREGNANT", "OPEN", "SERVED_OUT")


def assert_calving_event(data: dict):
    _assert_common(data)
    assert isinstance(data["animal_id"], str)
    assert isinstance(data["breeding_event_id"], str)
    assert isinstance(data["opened_lactation_id"], str)


def assert_health_treatment(data: dict):
    _assert_common(data)
    assert isinstance(data["animal_id"], str)
    assert isinstance(data["herd_id"], str)
    assert data["status"] in ("ACTIVE", "CLEARED", "VOIDED")


def assert_milk_check(data: dict):
    _assert_common(data)
    assert isinstance(data["herd_id"], str)
    assert isinstance(data["price_sheet_id"], str)
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "CANCELLED")
    for f in ("pooled_milk_lbs", "advance_paid", "gross_settlement", "net_payable"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_cull_decision(data: dict):
    _assert_common(data)
    assert isinstance(data["animal_id"], str)
    assert data["reason"] in ("LOW_PRODUCTION", "REPRO_FAILURE", "HIGH_SCC", "INJURY", "AGE")
    assert data["disposition"] in ("SLAUGHTER", "DAIRY_SALE", "DIED")
    assert data["status"] == "EXECUTED"
