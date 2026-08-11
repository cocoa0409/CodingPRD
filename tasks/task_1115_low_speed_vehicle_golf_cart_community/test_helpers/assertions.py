"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {type(value)}"
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_instant_equal(actual: str, expected: str):
    """Assert two ISO 8601 timestamps denote the same instant.

    PRD pins instants (e.g. §3.5 "valid_from is set to the activation instant",
    "expiry_date is set 365 days after valid_from") but does not pin the
    serialization of domain timestamp fields, so comparison is by instant.
    """
    assert is_iso8601_timestamp(actual), f"{actual!r} is not an ISO 8601 UTC timestamp"
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"instant mismatch: {actual!r} != {expected!r}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer starting at 1"


def assert_community(data: dict):
    """Validate a Community response against the PRD contract (§3.1)."""
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["min_driver_age"], int)
    assert isinstance(data["insurance_required"], bool)
    assert isinstance(data["fleet_program_enabled"], bool)
    assert isinstance(data["min_liability_coverage_cents"], int)
    assert isinstance(data["renewal_window_days"], int)
    assert isinstance(data["late_grace_days"], int)
    assert isinstance(data["checked_out_count"], int) and data["checked_out_count"] >= 0


def assert_permit_holder(data: dict):
    """Validate a PermitHolder response against the PRD contract (§3.2)."""
    _assert_common(data)
    assert is_valid_uuid(data.get("community_id", "")), "community_id must be a UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["birth_date"], str)
    assert data["driver_license_class"] in ["NONE", "STANDARD", "MOTORCYCLE"]
    assert data["eligibility_status"] in [
        "PENDING_VERIFICATION", "ELIGIBLE", "SUSPENDED", "REVOKED"]
    assert data["compliance_status"] in ["GOOD_STANDING", "PROBATION", "BARRED"]
    assert isinstance(data["points_balance"], int) and data["points_balance"] >= 0
    assert isinstance(data["wallet_balance_cents"], int) and data["wallet_balance_cents"] >= 0


def assert_vehicle(data: dict):
    """Validate a Vehicle response against the PRD contract (§3.3)."""
    _assert_common(data)
    assert is_valid_uuid(data.get("holder_id", "")), "holder_id must be a UUID"
    assert data["vehicle_type"] in ["GOLF_CART", "LSV"]
    assert isinstance(data["seat_count"], int) and 1 <= data["seat_count"] <= 8
    for flag in ["has_headlights", "has_brake_lights", "has_turn_signals", "has_horn",
                 "has_windshield", "has_seatbelts", "has_reflectors"]:
        assert isinstance(data[flag], bool), f"{flag} must be boolean"
    assert isinstance(data["mirror_count"], int) and 0 <= data["mirror_count"] <= 4
    assert isinstance(data["equipment_count"], int) and 0 <= data["equipment_count"] <= 8
    expected_count = (
        sum(1 for f in ["has_headlights", "has_brake_lights", "has_turn_signals",
                        "has_horn", "has_windshield", "has_seatbelts", "has_reflectors"]
            if data[f])
        + (1 if data["mirror_count"] >= 1 else 0)
    )
    assert data["equipment_count"] == expected_count, (
        f"equipment_count {data['equipment_count']} must equal the 7 true booleans "
        f"plus (mirror_count >= 1 ? 1 : 0) = {expected_count}"
    )
    assert data["vehicle_status"] in ["ACTIVE", "RETIRED"]


def assert_registration(data: dict):
    """Validate a VehicleRegistration response against the PRD contract (§3.3)."""
    _assert_common(data)
    assert is_valid_uuid(data.get("vehicle_id", "")), "vehicle_id must be a UUID"
    assert is_valid_uuid(data.get("holder_id", "")), "holder_id must be a UUID"
    assert isinstance(data["registration_year"], int)
    assert data["status"] in [
        "DRAFT", "ACTIVE", "RENEWAL_PENDING", "SUSPENDED", "EXPIRED", "REVOKED"]
    assert isinstance(data["provisional_fee_cents"], int)
    assert data.get("finalized_fee_cents") is None or isinstance(data["finalized_fee_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0


def assert_inspection(data: dict):
    """Validate an Inspection response against the PRD contract (§3.4)."""
    _assert_common(data)
    assert is_valid_uuid(data.get("registration_id", "")), "registration_id must be a UUID"
    assert isinstance(data["scheduled_at"], str)
    assert data["status"] in ["SCHEDULED", "PASSED", "FAILED"]


def assert_insurance_policy(data: dict):
    """Validate an InsurancePolicy response against the PRD contract (§3.5)."""
    _assert_common(data)
    assert is_valid_uuid(data.get("holder_id", "")), "holder_id must be a UUID"
    assert is_valid_uuid(data.get("vehicle_id", "")), "vehicle_id must be a UUID"
    assert isinstance(data["provider_name"], str)
    assert isinstance(data["policy_number"], str)
    assert isinstance(data["liability_coverage_cents"], int)
    assert data["status"] in ["ACTIVE", "CANCELLED", "EXPIRED"]


def assert_route(data: dict):
    """Validate a Route response against the PRD contract (§3.7)."""
    _assert_common(data)
    assert is_valid_uuid(data.get("community_id", "")), "community_id must be a UUID"
    assert isinstance(data["name"], str)
    assert data["route_type"] in ["STREET", "PATH"]
    assert data["allowed_vehicle_class"] in ["GOLF_CART_ONLY", "LSV_ALLOWED"]
    assert data["designation_status"] in ["DESIGNATED", "DECOMMISSIONED"]


def assert_route_pass(data: dict):
    """Validate a RoutePass response against the PRD contract (§3.7)."""
    _assert_common(data)
    assert is_valid_uuid(data.get("route_id", "")), "route_id must be a UUID"
    assert is_valid_uuid(data.get("registration_id", "")), "registration_id must be a UUID"
    assert is_valid_uuid(data.get("holder_id", "")), "holder_id must be a UUID"
    assert isinstance(data["start_at"], str)
    assert isinstance(data["end_at"], str)
    assert data["status"] in ["ACTIVE", "CANCELLED", "REVOKED", "COMPLETED"]


def assert_charging_station(data: dict):
    """Validate a ChargingStation response against the PRD contract (§3.8)."""
    _assert_common(data)
    assert is_valid_uuid(data.get("community_id", "")), "community_id must be a UUID"
    assert isinstance(data["name"], str)
    assert isinstance(data["slot_count"], int) and 1 <= data["slot_count"] <= 20
    assert isinstance(data["rate_cents_per_min"], int) and data["rate_cents_per_min"] >= 1
    assert data["status"] in ["ONLINE", "OFFLINE"]


def assert_charging_reservation(data: dict):
    """Validate a ChargingReservation response against the PRD contract (§3.8)."""
    _assert_common(data)
    assert is_valid_uuid(data.get("station_id", "")), "station_id must be a UUID"
    assert is_valid_uuid(data.get("holder_id", "")), "holder_id must be a UUID"
    assert isinstance(data["slot_index"], int) and data["slot_index"] >= 0
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in ["BOOKED", "CANCELLED", "COMPLETED"]


def assert_fleet_vehicle(data: dict):
    """Validate a FleetVehicle response against the PRD contract (§3.8)."""
    _assert_common(data)
    assert is_valid_uuid(data.get("community_id", "")), "community_id must be a UUID"
    assert is_valid_uuid(data.get("station_id", "")), "station_id must be a UUID"
    assert isinstance(data["label"], str)
    assert data["status"] in ["AVAILABLE", "CHECKED_OUT", "MAINTENANCE"]


def assert_fleet_dispatch(data: dict):
    """Validate a FleetDispatch response against the PRD contract (§3.8)."""
    _assert_common(data)
    assert is_valid_uuid(data.get("vehicle_id", "")), "vehicle_id must be a UUID"
    assert is_valid_uuid(data.get("holder_id", "")), "holder_id must be a UUID"
    assert isinstance(data["shift_start"], str)
    assert isinstance(data["shift_end"], str)
    assert data["status"] in ["BOOKED", "CHECKED_OUT", "OVERDUE", "RETURNED", "CANCELLED"]
    assert isinstance(data["late_fine_cents"], int) and data["late_fine_cents"] >= 0


def assert_violation(data: dict):
    """Validate a Violation response against the PRD contract (§3.9)."""
    _assert_common(data)
    assert is_valid_uuid(data.get("holder_id", "")), "holder_id must be a UUID"
    assert data["violation_code"] in [
        "UNDERAGE_DRIVER", "UNREGISTERED_VEHICLE", "EQUIPMENT_MISSING",
        "OFF_ROUTE", "PARKING_VIOLATION", "UNINSURED_OPERATION"]
    assert isinstance(data["points_assessed"], int) and 1 <= data["points_assessed"] <= 12
    assert isinstance(data["fine_cents"], int) and data["fine_cents"] >= 0
    assert data["status"] in ["FILED", "UPHELD", "DISMISSED"]


def assert_holder_invariants(data: dict):
    """Domain invariants that must hold on a PermitHolder after any operation
    (PRD §2.9 wallet never negative; §3.9 standing thresholds)."""
    assert data["wallet_balance_cents"] >= 0, "wallet must never go negative"
    pts = data["points_balance"]
    expected = ("BARRED" if pts >= 12 else "PROBATION" if pts >= 4 else "GOOD_STANDING")
    assert data["compliance_status"] == expected, (
        f"compliance_status {data['compliance_status']} inconsistent with "
        f"points_balance {pts} (expected {expected})"
    )
