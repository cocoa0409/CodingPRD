"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

COLD_STORAGE_STATUSES = ["AVAILABLE", "FULL"]
TEMP_ZONES = ["DRY", "REFRIGERATED", "FROZEN"]
FOOD_CATEGORIES = ["PRODUCE", "DAIRY", "FROZEN_MEAT", "DRY_GOODS", "BAKERY"]
SOURCE_TYPES = ["DONATION", "RESCUE", "TEFAP", "PURCHASED"]
LOT_DISPOSITIONS = ["AVAILABLE", "RESERVED", "DEPLETED", "EXPIRED", "DISPOSED"]
AGENCY_STATUSES = ["ACTIVE", "SUSPENDED"]
CYCLE_STATUSES = ["DRAFT", "OPEN", "CLOSED"]
ORDER_STATUSES = ["SUBMITTED", "APPROVED", "REJECTED", "FULFILLED", "CANCELLED"]
LINE_STATUSES = ["PENDING", "RESERVED", "SHORT", "PACKED"]
CERTIFICATION_STATUSES = ["PENDING", "CERTIFIED", "DENIED", "EXPIRED"]
EVENT_STATUSES = ["PLANNED", "PACKED", "FINALIZED", "VOIDED"]


def _assert_common_fields(data: dict):
    """id (UUID), created_at, updated_at (ISO8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must be >= 1, got {data['version']}"


def assert_cold_storage_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["temp_zone"] in TEMP_ZONES, f"bad temp_zone {data['temp_zone']!r}"
    assert data["capacity_lbs"] > 0, "capacity_lbs must be > 0"
    assert data["stored_lbs"] >= 0, "stored_lbs must be >= 0"
    assert data["status"] in COLD_STORAGE_STATUSES, f"bad status {data['status']!r}"


def assert_inventory_lot(data: dict):
    _assert_common_fields(data)
    assert data["food_category"] in FOOD_CATEGORIES, f"bad food_category {data['food_category']!r}"
    assert data["required_temp_zone"] in TEMP_ZONES, f"bad required_temp_zone {data['required_temp_zone']!r}"
    assert data["source_type"] in SOURCE_TYPES, f"bad source_type {data['source_type']!r}"
    assert data["intake_lbs"] > 0, "intake_lbs must be > 0"
    assert data["remaining_lbs"] >= 0, "remaining_lbs must be >= 0"
    assert data["unit_cost_cents"] >= 0, "unit_cost_cents must be >= 0"
    assert data["disposition"] in LOT_DISPOSITIONS, f"bad disposition {data['disposition']!r}"


def assert_agency(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["service_area"], str)
    assert data["fair_share_weight"] >= 1, "fair_share_weight must be >= 1"
    assert data["status"] in AGENCY_STATUSES, f"bad status {data['status']!r}"
    assert data["lifetime_distributed_lbs"] >= 0, "lifetime_distributed_lbs must be >= 0"


def assert_allocation_cycle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["total_pool_lbs"] > 0, "total_pool_lbs must be > 0"
    assert data["total_fair_share_weight"] >= 0, "total_fair_share_weight must be >= 0"
    assert data["status"] in CYCLE_STATUSES, f"bad status {data['status']!r}"


def assert_agency_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["agency_id"]), "agency_id must be a UUID"
    assert is_valid_uuid(data["allocation_cycle_id"]), "allocation_cycle_id must be a UUID"
    assert data["requested_lbs"] >= 0, "requested_lbs must be >= 0"
    assert data["approved_lbs"] >= 0, "approved_lbs must be >= 0"
    assert data["status"] in ORDER_STATUSES, f"bad status {data['status']!r}"


def assert_order_line(data: dict):
    _assert_common_fields(data)
    assert data["food_category"] in FOOD_CATEGORIES, f"bad food_category {data['food_category']!r}"
    assert data["requested_lbs"] > 0, "requested_lbs must be > 0"
    assert data["reserved_lbs"] >= 0, "reserved_lbs must be >= 0"
    assert data["line_status"] in LINE_STATUSES, f"bad line_status {data['line_status']!r}"


def assert_client_household(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["agency_id"]), "agency_id must be a UUID"
    assert data["household_size"] >= 1, "household_size must be >= 1"
    assert data["monthly_income_cents"] >= 0, "monthly_income_cents must be >= 0"
    assert isinstance(data["tefap_eligible"], bool), "tefap_eligible must be a bool"
    assert data["certification_status"] in CERTIFICATION_STATUSES, \
        f"bad certification_status {data['certification_status']!r}"


def assert_distribution_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["agency_order_id"]), "agency_order_id must be a UUID"
    assert is_valid_uuid(data["client_household_id"]), "client_household_id must be a UUID"
    assert data["planned_lbs"] >= 0, "planned_lbs must be >= 0"
    assert data["actual_distributed_lbs"] >= 0, "actual_distributed_lbs must be >= 0"
    assert data["tefap_lbs"] >= 0, "tefap_lbs must be >= 0"
    assert data["status"] in EVENT_STATUSES, f"bad status {data['status']!r}"


def assert_poundage_report(data: dict):
    """PoundageReport is a read-time snapshot: id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["allocation_cycle_id"]), "allocation_cycle_id must be a UUID"
