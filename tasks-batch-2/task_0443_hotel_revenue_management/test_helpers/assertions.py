"""Entity assertions and domain invariant checkers.

Field names mirror the Hotel Revenue Management API contract exactly.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

RATE_CLASSES = ["BAR", "CORPORATE", "ADVANCE_PURCHASE", "PACKAGE"]
RATE_PLAN_STATUSES = ["ACTIVE", "CLOSED"]
RATE_DECISION_STATUSES = ["DRAFT", "PUBLISHED", "REJECTED", "SUPERSEDED"]
GROUP_BLOCK_STATUSES = [
    "NEGOTIATING",
    "REVISION_REQUESTED",
    "COMMITTED",
    "CANCELLED",
    "LOST",
]
RESERVATION_STATUSES = ["HELD", "CONFIRMED", "CANCELLED", "CHECKED_OUT"]
CHANNELS = ["DIRECT", "OTA_A", "OTA_B", "GDS"]
PARITY_STATUSES = ["IN_PARITY", "OUT_OF_PARITY"]


def _assert_common_mutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer >= 1"
    )


def assert_property(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["total_rooms"], int) and data["total_rooms"] >= 1
    assert data["overbooking_limit_pct"] >= 0 and data["overbooking_limit_pct"] <= 0.30
    assert isinstance(data["currency"], str) and len(data["currency"]) > 0
    assert data["occupancy_pct"] >= 0
    assert data["adr"] >= 0
    assert data["revpar"] >= 0


def assert_room_type(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["physical_rooms"], int) and data["physical_rooms"] >= 1


def assert_rate_plan(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["room_type_id"])
    assert data["rate_class"] in RATE_CLASSES
    assert isinstance(data["is_master_bar"], bool)
    assert isinstance(data["min_los"], int) and data["min_los"] >= 1
    assert isinstance(data["max_los"], int) and data["max_los"] >= 0
    assert data["base_rate"] >= 0
    assert data["floor_rate"] >= 0
    assert data["ceiling_rate"] >= data["floor_rate"]
    assert data["status"] in RATE_PLAN_STATUSES
    assert data["published_rate"] is None or data["published_rate"] >= 0


def assert_inventory_day(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["room_type_id"])
    assert is_iso8601_timestamp(data["stay_date"])
    assert isinstance(data["physical_capacity"], int) and data["physical_capacity"] >= 0
    assert isinstance(data["group_held_rooms"], int) and data["group_held_rooms"] >= 0
    assert (
        isinstance(data["transient_sold_rooms"], int)
        and data["transient_sold_rooms"] >= 0
    )
    assert data["transient_revenue"] >= 0
    assert isinstance(data["rooms_sold"], int)
    assert isinstance(data["rooms_available"], int) and data["rooms_available"] >= 0
    assert data["rooms_sold"] == data["transient_sold_rooms"] + data["group_held_rooms"]


def assert_rate_decision(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["rate_plan_id"])
    assert is_iso8601_timestamp(data["stay_date"])
    assert data["status"] in RATE_DECISION_STATUSES
    assert data["requested_rate"] >= 0
    assert data["yielded_rate"] is None or data["yielded_rate"] >= 0
    assert isinstance(data["last_room_premium_applied"], bool)


def assert_yield_rule(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert 0 <= data["occupancy_threshold_pct"] <= 1
    assert isinstance(data["priority"], int) and data["priority"] >= 1
    assert isinstance(data["enabled"], bool)


def assert_group_block(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["room_type_id"])
    assert isinstance(data["group_name"], str) and len(data["group_name"]) > 0
    assert is_iso8601_timestamp(data["arrival_date"])
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    assert isinstance(data["rooms_per_night"], int) and data["rooms_per_night"] >= 1
    assert data["offered_rate"] >= 0
    assert data["status"] in GROUP_BLOCK_STATUSES
    assert data["recommendation"] in (None, "ACCEPT", "REJECT")


def assert_channel_mapping(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["rate_plan_id"])
    assert data["channel"] in CHANNELS
    assert data["markup_pct"] >= 0
    assert data["manual_rate_override"] is None or data["manual_rate_override"] >= 0
    assert data["parity_status"] in PARITY_STATUSES
    assert data["channel_rate"] is None or data["channel_rate"] >= 0


def assert_competitor_rate(data: dict):
    """CompetitorRate is immutable: id + created_at only, NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "CompetitorRate must not carry updated_at"
    assert "version" not in data, "CompetitorRate must not carry version"
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["competitor_name"], str) and len(data["competitor_name"]) > 0
    assert data["shopped_rate"] >= 0


def assert_transient_reservation(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["room_type_id"])
    assert is_valid_uuid(data["rate_plan_id"])
    assert is_iso8601_timestamp(data["arrival_date"])
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    assert isinstance(data["rooms"], int) and data["rooms"] >= 1
    assert data["status"] in RESERVATION_STATUSES
    assert data["booked_rate"] is None or data["booked_rate"] >= 0
