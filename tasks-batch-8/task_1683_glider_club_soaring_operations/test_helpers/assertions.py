"""Entity assertions and domain invariant checkers (PRD §2.2-§2.4, §3).

Each assert_* checks the structural contract of one resource: id is a bare
UUID, timestamps are ISO 8601 UTC, money fields are integer cents, and status
fields hold one of the PRD-named values. Value-level expectations belong in
the tests themselves.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AircraftStatus,
    AvailabilityStatus,
    BadgeLevel,
    DutySlotStatus,
    FlightStatus,
    MaintenanceKind,
    MemberStatus,
    ProgressKind,
    ProgressStatus,
    ReservationStatus,
    RetrieveStatus,
    TowSlotStatus,
    AircraftKind,
)


def _assert_common_fields(data: dict, entity: str):
    """PRD §2.4: every primary resource carries id, created_at, updated_at,
    and a version integer that increments on every mutation. (PRD does not pin
    the initial version value, so only the type is asserted here.)"""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and not isinstance(data.get("version"), bool), (
        f"{entity}.version must be an integer"
    )


def _assert_int_cents(data: dict, field: str, entity: str):
    assert isinstance(data.get(field), int) and not isinstance(data.get(field), bool), (
        f"{entity}.{field} must be integer cents (PRD §2.7)"
    )


def assert_membership_tier(data: dict):
    _assert_common_fields(data, "MembershipTier")
    assert isinstance(data["tier_code"], str) and data["tier_code"]
    _assert_int_cents(data, "monthly_dues_cents", "MembershipTier")
    assert isinstance(data["tow_fee_discount_pct"], (int, float))
    assert 0.0 <= data["tow_fee_discount_pct"] <= 0.50, (
        "tow_fee_discount_pct bounded inclusively between 0.00 and 0.50 (PRD §3.1)"
    )
    assert isinstance(data["included_tows_per_month"], int)
    assert isinstance(data["student_tier"], bool)


def assert_member(data: dict):
    _assert_common_fields(data, "Member")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data.get("tier_id", "")), "Member.tier_id must be a UUID"
    assert data["status"] in {s.value for s in MemberStatus}
    assert isinstance(data["is_instructor"], bool)
    assert isinstance(data["is_tow_pilot"], bool)
    _assert_int_cents(data, "account_balance_cents", "Member")
    _assert_int_cents(data, "pending_dues_cents", "Member")
    assert data.get("suspension_reason") is None or isinstance(data["suspension_reason"], str)
    assert isinstance(data["solo_endorsed"], bool)
    assert data["badge_level"] in {b.value for b in BadgeLevel}


def assert_aircraft(data: dict):
    _assert_common_fields(data, "Aircraft")
    assert isinstance(data["registration"], str) and data["registration"]
    assert data["kind"] in {k.value for k in AircraftKind}
    assert data["status"] in {s.value for s in AircraftStatus}
    assert isinstance(data["total_time_hours"], (int, float))
    assert isinstance(data["hours_since_inspection"], (int, float))
    assert isinstance(data["annual_due_date"], str)
    assert data.get("grounded_reason") is None or isinstance(data["grounded_reason"], str)


def assert_duty_slot(data: dict):
    _assert_common_fields(data, "DutyRosterSlot")
    assert isinstance(data["duty_date"], str)
    assert is_valid_uuid(data.get("member_id", "")), "DutyRosterSlot.member_id must be a UUID"
    assert data["status"] in {s.value for s in DutySlotStatus}
    assert data.get("swap_with_slot_id") is None or is_valid_uuid(data["swap_with_slot_id"])


def assert_availability(data: dict):
    _assert_common_fields(data, "InstructorAvailability")
    assert is_valid_uuid(data.get("instructor_id", ""))
    assert isinstance(data["start_at"], str)
    assert isinstance(data["end_at"], str)
    assert data["status"] in {s.value for s in AvailabilityStatus}


def assert_reservation(data: dict):
    _assert_common_fields(data, "Reservation")
    assert is_valid_uuid(data.get("aircraft_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert data.get("instructor_id") is None or is_valid_uuid(data["instructor_id"])
    assert isinstance(data["start_at"], str)
    assert isinstance(data["end_at"], str)
    assert data["status"] in {s.value for s in ReservationStatus}


def assert_flight(data: dict):
    _assert_common_fields(data, "Flight")
    assert is_valid_uuid(data.get("reservation_id", ""))
    assert is_valid_uuid(data.get("tow_slot_id", ""))
    assert isinstance(data["release_altitude_ft"], int)
    assert data["release_altitude_ft"] >= 500, "release altitude is at least 500 ft (PRD §3.5)"
    assert isinstance(data["takeoff_at"], str)
    assert data["status"] in {s.value for s in FlightStatus}
    _assert_int_cents(data, "provisional_fee_cents", "Flight")
    if data.get("landed_at") is not None:
        assert isinstance(data["landed_at"], str)
    if data.get("flight_minutes") is not None:
        assert isinstance(data["flight_minutes"], int)
    if data.get("final_fee_cents") is not None:
        _assert_int_cents(data, "final_fee_cents", "Flight")
    assert data.get("retrieve_id") is None or is_valid_uuid(data["retrieve_id"])


def assert_tow_slot(data: dict):
    _assert_common_fields(data, "TowSlot")
    assert is_valid_uuid(data.get("tow_plane_id", ""))
    assert is_valid_uuid(data.get("tow_pilot_id", ""))
    assert isinstance(data["start_at"], str)
    assert isinstance(data["end_at"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["confirmed_count"], int) and data["confirmed_count"] >= 0
    assert data["status"] in {s.value for s in TowSlotStatus}


def assert_maintenance_record(data: dict):
    """PRD §2.4: a MaintenanceRecord is an immutable log entry and carries only
    id and created_at; both updated_at and version are absent from it."""
    assert is_valid_uuid(data.get("id", "")), "MaintenanceRecord.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "MaintenanceRecord.created_at must be ISO 8601 UTC"
    )
    assert "updated_at" not in data, "MaintenanceRecord must not carry updated_at"
    assert "version" not in data, "MaintenanceRecord must not carry version"
    assert is_valid_uuid(data.get("aircraft_id", ""))
    assert data["kind"] in {k.value for k in MaintenanceKind}
    assert isinstance(data["performed_at"], str)
    assert isinstance(data["hobbs_hours_at_service"], (int, float))
    assert data.get("notes") is None or isinstance(data["notes"], str)


def assert_student_progress(data: dict):
    _assert_common_fields(data, "StudentProgress")
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("instructor_id", ""))
    assert data["kind"] in {k.value for k in ProgressKind}
    assert data["status"] in {s.value for s in ProgressStatus}
    if data.get("dual_hours_at_signoff") is not None:
        assert isinstance(data["dual_hours_at_signoff"], (int, float))
    assert data.get("signed_off_at") is None or isinstance(data["signed_off_at"], str)


def assert_retrieve(data: dict):
    _assert_common_fields(data, "RetrieveRequest")
    assert is_valid_uuid(data.get("flight_id", ""))
    assert isinstance(data["distance_km"], (int, float)) and data["distance_km"] > 0
    assert data["status"] in {s.value for s in RetrieveStatus}
    _assert_int_cents(data, "pilot_share_cents", "RetrieveRequest")
    _assert_int_cents(data, "club_share_cents", "RetrieveRequest")
    assert data.get("crew_member_id") is None or is_valid_uuid(data["crew_member_id"])


def assert_member_balance(data: dict, expected_cents: int):
    """Domain invariant: the member ledger reads exactly expected_cents."""
    assert_member(data)
    assert data["account_balance_cents"] == expected_cents, (
        f"Expected account_balance_cents {expected_cents}, "
        f"got {data['account_balance_cents']}"
    )
