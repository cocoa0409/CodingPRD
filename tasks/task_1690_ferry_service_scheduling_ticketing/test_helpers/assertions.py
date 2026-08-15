"""Entity assertions and domain invariant checkers.

Field names and value sets follow the PRD exactly. Nullable fields
(cancel_reason, vehicle_length_feet, final_fare_cents, rebooked_to_booking_id)
are type-checked only when present and non-null.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BookingStatus,
    CancelReason,
    CrewAssignmentStatus,
    CrewClass,
    CrewMemberStatus,
    CredentialClass,
    FareClass,
    FareScheduleStatus,
    PriorityClass,
    RouteStatus,
    SailingStatus,
    Season,
    StandbyStatus,
    VesselStatus,
)


def _assert_common(data: dict):
    """PRD §2.5 common fields: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_route(data: dict):
    _assert_common(data)
    assert isinstance(data["route_code"], str) and len(data["route_code"]) > 0
    assert isinstance(data["origin_terminal"], str) and len(data["origin_terminal"]) > 0
    assert isinstance(data["destination_terminal"], str) and len(data["destination_terminal"]) > 0
    assert isinstance(data["crossing_minutes"], int) and data["crossing_minutes"] > 0
    assert isinstance(data["turnaround_minutes"], int) and data["turnaround_minutes"] >= 0
    assert data["status"] in [s.value for s in RouteStatus]


def assert_vessel(data: dict):
    _assert_common(data)
    assert isinstance(data["vessel_name"], str) and len(data["vessel_name"]) > 0
    assert isinstance(data["vehicle_deck_linear_feet"], int) and data["vehicle_deck_linear_feet"] > 0
    assert isinstance(data["passenger_capacity"], int) and data["passenger_capacity"] > 0
    assert data["crew_class"] in [c.value for c in CrewClass]
    assert data["status"] in [s.value for s in VesselStatus]


def assert_fare_schedule(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("route_id", ""))
    assert data["season"] in [s.value for s in Season]
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))
    for field in (
        "passenger_standard_cents",
        "passenger_resident_cents",
        "passenger_commuter_cents",
        "vehicle_standard_base_cents",
        "vehicle_oversize_base_cents",
        "vehicle_overlength_per_foot_cents",
        "fuel_surcharge_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be non-negative integer cents, got {data.get(field)!r}"
        )
    assert data["status"] in [s.value for s in FareScheduleStatus]


def assert_sailing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("route_id", ""))
    assert is_valid_uuid(data.get("vessel_id", ""))
    assert is_iso8601_timestamp(data.get("departure_time", ""))
    assert is_iso8601_timestamp(data.get("arrival_time", ""))
    assert data["season"] in [s.value for s in Season]
    assert data["status"] in [s.value for s in SailingStatus]
    if data.get("cancel_reason") is not None:
        assert data["cancel_reason"] in [r.value for r in CancelReason]
    for field in (
        "reserved_vehicle_feet",
        "standby_cleared_feet",
        "booked_passengers",
        "reserved_deck_allotment_feet",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data.get(field)!r}"
        )
    assert isinstance(data["manning_ok"], bool)


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["fare_class"] in [c.value for c in FareClass]
    # PRD §3.5: refund_credit_cents starts at 0 and may never go negative.
    assert isinstance(data["refund_credit_cents"], int) and data["refund_credit_cents"] >= 0


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sailing_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("fare_schedule_id", ""))
    assert isinstance(data["passenger_count"], int) and data["passenger_count"] >= 0
    assert isinstance(data["has_vehicle"], bool)
    if data.get("vehicle_length_feet") is not None:
        assert isinstance(data["vehicle_length_feet"], int)
    assert data["status"] in [s.value for s in BookingStatus]
    assert isinstance(data["quoted_fare_cents"], int) and data["quoted_fare_cents"] >= 0
    if data.get("final_fare_cents") is not None:
        assert isinstance(data["final_fare_cents"], int) and data["final_fare_cents"] >= 0
    if data.get("rebooked_to_booking_id") is not None:
        assert is_valid_uuid(data["rebooked_to_booking_id"])


def assert_standby_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sailing_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["has_vehicle"], bool)
    if data.get("vehicle_length_feet") is not None:
        assert isinstance(data["vehicle_length_feet"], int)
    assert isinstance(data["passenger_count"], int) and data["passenger_count"] >= 1
    assert data["priority_class"] in [c.value for c in PriorityClass]
    assert is_iso8601_timestamp(data.get("queued_at", ""))
    assert data["status"] in [s.value for s in StandbyStatus]


def assert_crew_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["credential_class"] in [c.value for c in CredentialClass]
    assert data["status"] in [s.value for s in CrewMemberStatus]


def assert_crew_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sailing_id", ""))
    assert is_valid_uuid(data.get("crew_member_id", ""))
    assert is_iso8601_timestamp(data.get("shift_start", ""))
    assert is_iso8601_timestamp(data.get("shift_end", ""))
    assert data["status"] in [s.value for s in CrewAssignmentStatus]


def assert_deck_partition(sailing: dict, vehicle_deck_linear_feet: int):
    """PRD §2.7: the reservation pool plus the standby pool (the remainder)
    always equals the vessel's full deck footage, and reserved feet held may
    never exceed the pinned reservation pool."""
    allotment = sailing["reserved_deck_allotment_feet"]
    assert 0 <= allotment <= vehicle_deck_linear_feet, (
        f"reserved_deck_allotment_feet {allotment} outside deck budget {vehicle_deck_linear_feet}"
    )
    assert sailing["reserved_vehicle_feet"] <= allotment, (
        f"reserved_vehicle_feet {sailing['reserved_vehicle_feet']} exceeds pinned allotment {allotment}"
    )
