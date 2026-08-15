"""Entity assertions and domain invariant checkers.

Structural assertions only: identity, timestamp formats, enum membership, and
field presence/type. Nullable computed fields are checked for type only when
present and non-null.
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a comparable datetime.

    The PRD pins the logical clock default to the instant 2026-08-01T00:00:00Z
    while timestamps serialize with three fractional digits, so tests compare
    parsed instants rather than raw strings.
    """
    assert isinstance(ts, str) and ts, f"Expected a timestamp string, got {ts!r}"
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def assert_same_instant(actual_ts: str, expected_iso: str, label: str = "timestamp"):
    """Two timestamp strings denote the same instant (formatting may differ)."""
    assert parse_instant(actual_ts) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual_ts}"
    )


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_optional_ts(data: dict, field: str, entity: str):
    if data.get(field) is not None:
        assert is_iso8601_timestamp(data[field]), (
            f"{entity}.{field} must be ISO 8601 when present"
        )


def _assert_optional_number(data: dict, field: str, entity: str):
    if data.get(field) is not None:
        assert isinstance(data[field], (int, float)) and not isinstance(data[field], bool), (
            f"{entity}.{field} must be numeric when present"
        )


def assert_grower(data: dict):
    _assert_common_fields(data, "Grower")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["grower_code"], str) and data["grower_code"]


def assert_orchard_block(data: dict):
    _assert_common_fields(data, "OrchardBlock")
    assert is_valid_uuid(data.get("grower_id", "")), "OrchardBlock.grower_id must be a UUID"
    assert isinstance(data["orchard_name"], str) and data["orchard_name"]
    assert isinstance(data["block_code"], str) and data["block_code"]
    assert data["variety"] in [
        "HONEYCRISP", "GALA", "FUJI", "GRANNY_SMITH", "COSMIC_CRISP",
    ]
    assert isinstance(data["storage_life_days"], int) and data["storage_life_days"] > 0


def assert_lot(data: dict):
    _assert_common_fields(data, "Lot")
    assert is_valid_uuid(data.get("grower_id", "")), "Lot.grower_id must be a UUID"
    assert is_valid_uuid(data.get("block_id", "")), "Lot.block_id must be a UUID"
    assert isinstance(data["received_bin_count"], int) and data["received_bin_count"] > 0
    assert data["received_weight_lbs"] > 0
    assert 0 <= data["avg_color_pct"] <= 100
    _assert_optional_ts(data, "received_at", "Lot")
    for field in ("size_small_lbs", "size_medium_lbs", "size_large_lbs",
                  "presize_cull_lbs", "diverted_weight_lbs", "weight_balance_lbs"):
        assert isinstance(data[field], (int, float)), f"Lot.{field} must be numeric"
    _assert_optional_number(data, "est_packout_pct", "Lot")
    _assert_optional_number(data, "actual_packout_pct", "Lot")
    assert data["status"] in [
        "RECEIVED", "PRESIZED", "IN_STORAGE", "RELEASED", "PACKED", "CLOSED", "DIVERTED",
    ]


def assert_ca_room(data: dict):
    _assert_common_fields(data, "CARoom")
    assert isinstance(data["room_code"], str) and data["room_code"]
    assert isinstance(data["bin_capacity"], int) and data["bin_capacity"] > 0
    assert 0.1 <= data["o2_setpoint_pct"] <= 21.0
    assert isinstance(data["current_o2_pct"], (int, float))
    assert isinstance(data["atmosphere_alarm"], bool)
    assert isinstance(data["o2_excursion_count"], int)
    assert isinstance(data["disorder_index"], (int, float))
    assert isinstance(data["priority_release"], bool)
    assert isinstance(data["bins_allocated"], int)
    assert isinstance(data["bins_free"], int)
    assert data["bins_free"] == data["bin_capacity"] - data["bins_allocated"], (
        "bins_free must equal bin_capacity - bins_allocated"
    )
    _assert_optional_ts(data, "sealed_at", "CARoom")
    _assert_optional_ts(data, "planned_open_date", "CARoom")
    _assert_optional_ts(data, "actual_opened_at", "CARoom")
    _assert_optional_ts(data, "must_empty_by", "CARoom")
    assert data["status"] in ["AVAILABLE", "FILLING", "SEALED", "OPENED"]


def assert_storage_allocation(data: dict):
    _assert_common_fields(data, "StorageAllocation")
    assert is_valid_uuid(data.get("room_id", "")), "StorageAllocation.room_id must be a UUID"
    assert is_valid_uuid(data.get("lot_id", "")), "StorageAllocation.lot_id must be a UUID"
    assert isinstance(data["bins"], int) and data["bins"] > 0
    assert data["status"] in ["ACTIVE", "RELEASED"]
    if data["status"] == "ACTIVE":
        assert data.get("released_at") is None, "released_at stays null while ACTIVE"
        assert data.get("release_reason") is None, "release_reason stays null while ACTIVE"
    else:
        assert data.get("release_reason") in ["MANUAL", "SELECTED", "DIVERSION"]
        _assert_optional_ts(data, "released_at", "StorageAllocation")
    _assert_optional_ts(data, "allocated_at", "StorageAllocation")
    _assert_optional_ts(data, "must_release_by", "StorageAllocation")
    _assert_optional_number(data, "release_priority_score", "StorageAllocation")


def assert_disorder_inspection(data: dict):
    """Append-only event: id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "DisorderInspection.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "DisorderInspection.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "Append-only inspection must not carry updated_at"
    assert "version" not in data, "Append-only inspection must not carry version"
    assert is_valid_uuid(data.get("room_id", "")), "DisorderInspection.room_id must be a UUID"
    for field in ("scald_pct", "bitter_pit_pct", "decay_pct"):
        assert 0 <= data[field] <= 100, f"DisorderInspection.{field} within 0..100"
    _assert_optional_number(data, "disorder_index", "DisorderInspection")
    _assert_optional_ts(data, "inspected_at", "DisorderInspection")


def assert_packaging_spec(data: dict):
    _assert_common_fields(data, "PackagingSpec")
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert isinstance(data["label_code"], str) and data["label_code"]
    assert data["grade_min"] in ["EXTRA_FANCY", "FANCY", "UTILITY"]
    assert isinstance(data["color_min_pct"], int) and 0 <= data["color_min_pct"] <= 100
    assert data["size_class"] in ["SMALL", "MEDIUM", "LARGE"]
    assert data["pack_style"] in ["TRAY", "BAG", "POUCH"]
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]


def assert_packing_run(data: dict):
    _assert_common_fields(data, "PackingRun")
    assert is_valid_uuid(data.get("lot_id", "")), "PackingRun.lot_id must be a UUID"
    assert is_valid_uuid(data.get("spec_id", "")), "PackingRun.spec_id must be a UUID"
    assert is_valid_uuid(data.get("pool_id", "")), "PackingRun.pool_id must be a UUID"
    assert isinstance(data["line_code"], str) and data["line_code"]
    _assert_optional_ts(data, "scheduled_start", "PackingRun")
    _assert_optional_ts(data, "scheduled_end", "PackingRun")
    assert data["input_weight_lbs"] > 0
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED", "VOIDED"]
    if data["status"] == "COMPLETED":
        assert isinstance(data["cartons_produced"], int) and data["cartons_produced"] >= 0
        for field in ("packed_weight_lbs", "cull_weight_lbs", "juice_weight_lbs"):
            assert data[field] >= 0, f"PackingRun.{field} must be non-negative"
        _assert_optional_number(data, "packout_pct", "PackingRun")


def assert_pool(data: dict):
    _assert_common_fields(data, "Pool")
    assert data["variety"] in [
        "HONEYCRISP", "GALA", "FUJI", "GRANNY_SMITH", "COSMIC_CRISP",
    ]
    assert data["grade_class"] in ["EXTRA_FANCY", "FANCY", "UTILITY"]
    assert isinstance(data["season"], str) and data["season"]
    for field in ("total_packed_cartons", "total_sales_cents",
                  "total_sale_deductions_cents", "total_deductions_cents"):
        assert isinstance(data[field], int), f"Pool.{field} must be an integer"
    _assert_optional_number(data, "estimated_price_cents", "Pool")
    _assert_optional_number(data, "pool_price_per_carton_cents", "Pool")
    _assert_optional_number(data, "rounding_drift_cents", "Pool")
    assert data["status"] in ["OPEN", "CLOSED", "REOPENED"]


def assert_grower_settlement(data: dict):
    _assert_common_fields(data, "GrowerSettlement")
    assert is_valid_uuid(data.get("grower_id", "")), "GrowerSettlement.grower_id must be a UUID"
    assert is_valid_uuid(data.get("pool_id", "")), "GrowerSettlement.pool_id must be a UUID"
    for field in ("attributed_cartons", "advance_amount_cents", "final_payment_cents",
                  "paid_final_cents", "clawback_cents"):
        assert isinstance(data[field], int), f"GrowerSettlement.{field} must be an integer"
    assert data["status"] in ["ACCRUING", "ADVANCE_PAID", "SETTLED"]
