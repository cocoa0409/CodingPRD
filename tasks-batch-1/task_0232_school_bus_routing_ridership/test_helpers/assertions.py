"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Each assert_{entity}() validates the response shape against the PRD contract.
Append-only records (TapEvent, ParentNotification) are checked to carry id +
created_at and to OMIT updated_at / version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (PRD §2.4 common quartet)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_event_fields(data: dict):
    """id + created_at only — append-only records (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must omit updated_at"
    assert "version" not in data, "append-only record must omit version"


def assert_district(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["school_lat"], (int, float))
    assert isinstance(data["school_lng"], (int, float))
    assert isinstance(data["walk_threshold_miles"], (int, float))
    assert isinstance(data["hazard_override_enabled"], bool)
    assert isinstance(data["missed_bus_grace_minutes"], int)
    assert isinstance(data["service_day_index"], int)
    assert isinstance(data["active_route_count"], int)


def assert_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["district_id"], str)
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] > 0
    assert isinstance(data["wheelchair_capacity"], int) and data["wheelchair_capacity"] >= 0
    assert data["posture"] in ("OPEN", "RESTRICTED", "SUSPENDED")
    assert isinstance(data["assigned_rider_count"], int) and data["assigned_rider_count"] >= 0
    assert isinstance(data["assigned_wheelchair_count"], int)
    assert isinstance(data["open_incident"], bool)


def assert_stop(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["route_id"], str)
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["scheduled_departure"], str)


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["district_id"], str)
    assert isinstance(data["parent_id"], str)
    assert isinstance(data["grade"], int) and 0 <= data["grade"] <= 12
    assert isinstance(data["hazard_zone"], bool)
    assert isinstance(data["special_needs"], bool)
    assert isinstance(data["rfid_uid"], str)
    assert isinstance(data["home_distance_miles"], (int, float))


def assert_application(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED",
        "APPROVED", "DENIED", "WITHDRAWN",
    )
    assert data["eligibility_basis"] in ("PENDING", "DISTANCE", "HAZARD", "NONE")
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0


def assert_driver(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["district_id"], str)
    assert isinstance(data["is_substitute"], bool)
    assert data["status"] in ("AVAILABLE", "ON_DUTY")


def assert_driver_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["route_id"], str)
    assert isinstance(data["driver_id"], str)
    assert data["role"] in ("PRIMARY", "SUBSTITUTE")
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_bus_trip(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["route_id"], str)
    assert isinstance(data["driver_assignment_id"], str)
    assert data["status"] in (
        "SCHEDULED", "BOARDING", "IN_TRANSIT",
        "INCIDENT_HOLD", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["current_stop_sequence"], int)
    assert isinstance(data["onboard_count"], int) and data["onboard_count"] >= 0
    assert isinstance(data["incident_count"], int) and data["incident_count"] >= 0


def assert_missed_bus_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["district_id"], str)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["bus_trip_id"], str)
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "RESOLVED")


def assert_tap_event(data: dict):
    _assert_event_fields(data)
    assert isinstance(data["bus_trip_id"], str)
    assert data["direction"] in ("TAP_ON", "TAP_OFF")


def assert_parent_notification(data: dict):
    _assert_event_fields(data)
    assert data["kind"] in (
        "TAP_ON", "TAP_OFF", "MISSED_BUS", "INCIDENT", "APPLICATION_DECISION",
    )
