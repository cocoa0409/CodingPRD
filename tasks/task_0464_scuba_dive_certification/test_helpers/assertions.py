"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. CertificationCard and Waiver are immutable (no updated_at/version)
and their assertions reflect that.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

CERT_LEVELS = ["NONE", "OPEN_WATER", "ADVANCED"]
MEDICAL_STATUSES = ["UNKNOWN", "CLEAR", "RESTRICTED"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at >= 1, got {data['version']}"


def _assert_immutable_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable entity must not carry a version field"
    assert "updated_at" not in data, "immutable entity must not carry an updated_at field"


def assert_diver(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["cert_level"] in CERT_LEVELS, f"unexpected cert_level {data['cert_level']!r}"
    assert isinstance(data["nitrox_certified"], bool)
    assert data["medical_status"] in MEDICAL_STATUSES
    assert isinstance(data["deposit_on_hold_cents"], int)
    assert data["deposit_on_hold_cents"] >= 0, "deposit_on_hold_cents must be >= 0"


def assert_instructor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["rating"] in ["DIVEMASTER", "INSTRUCTOR"]
    assert isinstance(data["active_session_count"], int)
    assert data["active_session_count"] >= 0


def assert_course(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["course_type"] in ["OPEN_WATER", "ADVANCED"]
    assert isinstance(data["required_pool_sessions"], int) and data["required_pool_sessions"] >= 0
    assert isinstance(data["required_open_water_sessions"], int) and data["required_open_water_sessions"] >= 1
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert data["grants_specialty"] in ["NONE", "ENRICHED_AIR"]


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["diver_id"])
    assert is_valid_uuid(data["course_id"])
    assert data["status"] in ["ACTIVE", "ELIGIBLE", "COMPLETED", "WITHDRAWN"]
    assert isinstance(data["elearning_pct"], int) and 0 <= data["elearning_pct"] <= 100
    assert isinstance(data["pool_sessions_attended"], int) and data["pool_sessions_attended"] >= 0
    assert isinstance(data["open_water_sessions_attended"], int) and data["open_water_sessions_attended"] >= 0
    assert isinstance(data["completion_pct"], int) and 0 <= data["completion_pct"] <= 100


def assert_session(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["course_id"])
    assert is_valid_uuid(data["primary_instructor_id"])
    assert data["session_type"] in ["POOL", "OPEN_WATER"]
    assert isinstance(data["assistant_count"], int) and data["assistant_count"] >= 0
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["max_students"], int) and data["max_students"] >= 0
    assert isinstance(data["confirmed_seats"], int) and data["confirmed_seats"] >= 0
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_session_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["enrollment_id"])
    assert data["status"] in ["BOOKED", "ATTENDED", "CANCELLED", "NO_SHOW"]


def assert_certification_card(data: dict):
    _assert_immutable_common_fields(data)
    assert is_valid_uuid(data["diver_id"])
    assert is_valid_uuid(data["enrollment_id"])
    assert data["level"] in ["OPEN_WATER", "ADVANCED"]
    assert data["specialty"] in ["NONE", "ENRICHED_AIR"]
    assert is_iso8601_timestamp(data["issued_at"])


def assert_waiver(data: dict):
    _assert_immutable_common_fields(data)
    assert is_valid_uuid(data["diver_id"])
    assert isinstance(data["medical_flagged"], bool)
    assert is_iso8601_timestamp(data["signed_at"])
    assert is_iso8601_timestamp(data["expires_at"])


def assert_boat(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["turnaround_minutes"], int) and data["turnaround_minutes"] >= 0


def assert_dive_trip(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["boat_id"])
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["min_cert_level"] in ["OPEN_WATER", "ADVANCED"]
    assert isinstance(data["base_fare_cents"], int) and data["base_fare_cents"] > 0
    assert isinstance(data["fill_addon_cents"], int) and data["fill_addon_cents"] >= 0
    assert isinstance(data["confirmed_divers"], int) and data["confirmed_divers"] >= 0
    assert data["status"] in ["OPEN", "DEPARTED", "CANCELLED"]


def assert_trip_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["trip_id"])
    assert is_valid_uuid(data["diver_id"])
    assert isinstance(data["tanks"], int) and data["tanks"] >= 0
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["deposit_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert data["status"] in ["CONFIRMED", "CANCELLED", "DEPARTED"]


def assert_rental_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["diver_id"])
    assert isinstance(data["item_description"], str)
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] > 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert is_iso8601_timestamp(data["checkout_at"])
    assert is_iso8601_timestamp(data["scheduled_return_at"])
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["status"] in ["ACTIVE", "RETURNED", "VOIDED"]


def assert_fill_service(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["diver_id"])
    assert data["gas"] in ["AIR", "NITROX"]
    assert isinstance(data["o2_pct"], int)
    assert isinstance(data["tank_capacity_liters"], int) and data["tank_capacity_liters"] > 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0


def assert_gear_service_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["diver_id"])
    assert data["service_type"] in ["VIP", "HYDRO"]
    assert data["status"] in ["OPEN", "COMPLETED", "CANCELLED"]
