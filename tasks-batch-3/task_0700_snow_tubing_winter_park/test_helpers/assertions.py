"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) validates structural shape and field domains for a
returned resource. Append-only logs (WeatherLog, RefundEntry) carry only
id + created_at — they are NOT checked for updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# Domain enum value sets.
_PARK_POSTURES = {"OPEN", "RESTRICTED", "CLOSED"}
_LANE_STATUSES = {"OPEN", "GROOMING", "CLOSED"}
_LANE_CLOSURE_REASONS = {"WEATHER", "MAINTENANCE", "GROUP_RENTAL", None}
_TIME_BLOCK_STATUSES = {"SCHEDULED", "ACTIVE", "SWEPT"}
_TICKET_LIFECYCLE = {"RESERVED", "CONFIRMED", "REDEEMED", "EXPIRED", "REFUNDED"}
_TICKET_CHECKIN = {"NOT_CHECKED_IN", "GEARED_UP", "ON_LANE"}
_WAIVER_STATUSES = {"ACTIVE", "REVOKED"}
_PASS_TIERS = {"SILVER", "GOLD", "RESIDENT_GOLD"}
_PASS_STATUSES = {"ACTIVE", "SUSPENDED", "EXPIRED"}
_GROUP_RENTAL_TYPES = {"SHARED_SEATS", "EXCLUSIVE_LANE"}
_GROUP_STATES = {"DRAFT", "HELD", "CONFIRMED", "CANCELLED"}
_EQUIP_TYPES = {"TUBE", "HELMET", "BOOTS"}
_TUBE_SIZES = {"SMALL", "MEDIUM", "LARGE", None}
_EQUIP_STATES = {"DISPATCHED", "RETURNED", "DAMAGED"}
_TURN_STATES = {"BOARDED", "CLEARED"}
_ADDON_CATEGORIES = {"FOOD", "RENTAL_UPGRADE", "HOT_DRINK"}
_ADDON_STATES = {"ORDERED", "FULFILLED", "VOIDED"}
_REFUND_REASONS = {"WEATHER_CLOSURE", "PATRON_CANCEL", "GROUP_CANCEL"}


def _assert_common_audit_fields(data: dict):
    """id + created_at + updated_at + version for mutable resources."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def _assert_append_only_fields(data: dict):
    """id + created_at ONLY for append-only logs."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_park(data: dict):
    _assert_common_audit_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["operational_posture"] in _PARK_POSTURES
    assert isinstance(data["open_lane_count"], int) and data["open_lane_count"] >= 0
    assert isinstance(data["total_capacity_remaining"], int)
    assert isinstance(data["min_snow_depth_cm"], int)
    assert isinstance(data["max_safe_wind_kph"], int)
    assert isinstance(data["resident_zip_prefixes"], list)


def assert_lane(data: dict):
    _assert_common_audit_fields(data)
    assert is_valid_uuid(data.get("park_id", "")), "park_id must be a UUID"
    assert isinstance(data["label"], str)
    assert isinstance(data["rider_capacity_per_block"], int) and data["rider_capacity_per_block"] >= 1
    assert isinstance(data["conveyor_cycle_seconds"], int) and data["conveyor_cycle_seconds"] >= 1
    assert data["status"] in _LANE_STATUSES
    assert data["closure_reason"] in _LANE_CLOSURE_REASONS


def assert_time_block(data: dict):
    _assert_common_audit_fields(data)
    assert is_valid_uuid(data.get("park_id", "")), "park_id must be a UUID"
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["status"] in _TIME_BLOCK_STATUSES
    assert isinstance(data["committed_rider_count"], int) and data["committed_rider_count"] >= 0


def assert_session_ticket(data: dict):
    _assert_common_audit_fields(data)
    assert is_valid_uuid(data.get("park_id", "")), "park_id must be a UUID"
    assert is_valid_uuid(data.get("time_block_id", "")), "time_block_id must be a UUID"
    assert is_valid_uuid(data.get("holder_patron_id", "")), "holder_patron_id must be a UUID"
    assert isinstance(data["rider_height_cm"], int)
    assert isinstance(data["rider_age_years"], int)
    assert isinstance(data["is_resident"], bool)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert data["lifecycle_state"] in _TICKET_LIFECYCLE
    assert data["checkin_state"] in _TICKET_CHECKIN


def assert_waiver(data: dict):
    _assert_common_audit_fields(data)
    assert is_valid_uuid(data.get("patron_id", "")), "patron_id must be a UUID"
    assert is_valid_uuid(data.get("park_id", "")), "park_id must be a UUID"
    assert is_iso8601_timestamp(data["signed_at"])
    assert data["status"] in _WAIVER_STATUSES


def assert_season_pass(data: dict):
    _assert_common_audit_fields(data)
    assert is_valid_uuid(data.get("park_id", "")), "park_id must be a UUID"
    assert is_valid_uuid(data.get("holder_patron_id", "")), "holder_patron_id must be a UUID"
    assert data["tier"] in _PASS_TIERS
    assert data["status"] in _PASS_STATUSES
    assert isinstance(data["redemptions_today_count"], int) and data["redemptions_today_count"] >= 0


def assert_group_reservation(data: dict):
    _assert_common_audit_fields(data)
    assert is_valid_uuid(data.get("park_id", "")), "park_id must be a UUID"
    assert is_valid_uuid(data.get("host_patron_id", "")), "host_patron_id must be a UUID"
    assert is_valid_uuid(data.get("time_block_id", "")), "time_block_id must be a UUID"
    assert data["rental_type"] in _GROUP_RENTAL_TYPES
    assert isinstance(data["party_size"], int) and data["party_size"] >= 2
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["state"] in _GROUP_STATES


def assert_equipment_rental(data: dict):
    _assert_common_audit_fields(data)
    assert is_valid_uuid(data.get("ticket_id", "")), "ticket_id must be a UUID"
    assert data["equipment_type"] in _EQUIP_TYPES
    assert data.get("tube_size") in _TUBE_SIZES
    assert data["state"] in _EQUIP_STATES


def assert_conveyor_turn(data: dict):
    _assert_common_audit_fields(data)
    assert is_valid_uuid(data.get("lane_id", "")), "lane_id must be a UUID"
    assert is_valid_uuid(data.get("time_block_id", "")), "time_block_id must be a UUID"
    assert is_valid_uuid(data.get("ticket_id", "")), "ticket_id must be a UUID"
    assert is_iso8601_timestamp(data["boarded_at"])
    assert is_iso8601_timestamp(data["cleared_at"])
    assert data["state"] in _TURN_STATES


def assert_add_on(data: dict):
    _assert_common_audit_fields(data)
    assert is_valid_uuid(data.get("park_id", "")), "park_id must be a UUID"
    assert is_valid_uuid(data.get("ticket_id", "")), "ticket_id must be a UUID"
    assert data["category"] in _ADDON_CATEGORIES
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] >= 0
    assert data["state"] in _ADDON_STATES


def assert_patron(data: dict):
    _assert_common_audit_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["zip_code"], str)


def assert_weather_log(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("park_id", "")), "park_id must be a UUID"
    assert is_iso8601_timestamp(data["observed_at"])
    assert isinstance(data["snow_depth_cm"], int) and data["snow_depth_cm"] >= 0
    assert isinstance(data["wind_kph"], int) and data["wind_kph"] >= 0
    assert data["derived_posture"] in _PARK_POSTURES


def assert_refund_entry(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["reason"] in _REFUND_REASONS
