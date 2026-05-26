"""Entity assertions and domain invariant checkers.

Per PRD §2.4 every primary resource carries (id, created_at, updated_at, version).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ---------------------------------------------------------------------
# Common-fields quartet (PRD §2.4)
# ---------------------------------------------------------------------
def _assert_common_fields(data: dict, entity_name: str = "resource") -> None:
    assert "id" in data, f"{entity_name} missing 'id'"
    assert is_valid_uuid(data["id"]), (
        f"{entity_name}.id must be a server-minted UUID, got {data['id']!r}"
    )
    # PRD §2.4: UUID with no type prefix.
    assert "_" not in data["id"], (
        f"{entity_name}.id must be raw UUID, no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, f"{entity_name} missing 'created_at'"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"{entity_name}.created_at must be ISO 8601 UTC, got {data['created_at']!r}"
    )
    assert "updated_at" in data, f"{entity_name} missing 'updated_at'"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"{entity_name}.updated_at must be ISO 8601 UTC, got {data['updated_at']!r}"
    )
    assert "version" in data, f"{entity_name} missing 'version'"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity_name}.version must be int >= 1, got {data['version']!r}"
    )


# ---------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------
VALID_RANKS = {"CAPTAIN", "FIRST_OFFICER", "PURSER", "FLIGHT_ATTENDANT"}
VALID_LINE_TYPES = {"LINEHOLDER", "RESERVE"}
VALID_CREW_STATUSES = {"AVAILABLE", "ON_DUTY", "ON_REST", "SICK", "INACTIVE"}
VALID_PAIRING_STATES = {
    "DRAFT", "BID_OPEN", "BID_CLOSED", "AWARDED",
    "IN_PROGRESS", "COMPLETED", "CANCELLED",
}
VALID_BID_STATES = {"SUBMITTED", "AWARDED", "UNSUCCESSFUL", "WITHDRAWN"}
VALID_ASSIGNMENT_STATES = {
    "SCHEDULED", "CONFIRMED", "ACTIVE", "COMPLETED",
    "RELEASED", "RECOVERED", "CANCELLED",
}
VALID_ASSIGNMENT_SOURCES = {"BID_AWARD", "RESERVE_CALLUP", "TRIP_TRADE"}
VALID_SEATS = {"CAPTAIN", "FIRST_OFFICER", "PURSER", "FLIGHT_ATTENDANT"}
VALID_LEG_TYPES = {"REVENUE", "DEADHEAD"}
VALID_SICK_REASON_CODES = {"ILLNESS", "INJURY", "FAMILY_EMERGENCY"}
VALID_SICK_CALL_STATES = {"REPORTED", "ACKNOWLEDGED", "CLOSED"}
VALID_RESERVE_CALLUP_STATES = {"OFFERED", "ACCEPTED", "DECLINED", "EXPIRED"}
VALID_TRIP_TRADE_STATES = {
    "PROPOSED", "COUNTERSIGNED", "APPROVED",
    "EXECUTED", "REJECTED", "WITHDRAWN",
}


def assert_crew_member(data: dict) -> None:
    _assert_common_fields(data, "CrewMember")
    assert data["rank"] in VALID_RANKS, f"crew rank invalid: {data['rank']!r}"
    assert data["line_type"] in VALID_LINE_TYPES, (
        f"crew line_type invalid: {data['line_type']!r}"
    )
    assert data["status"] in VALID_CREW_STATUSES, (
        f"crew status invalid: {data['status']!r}"
    )
    assert isinstance(data["seniority_number"], int)
    assert data["seniority_number"] >= 1
    assert isinstance(data["total_flight_minutes_7d"], int)
    assert isinstance(data["total_duty_minutes_7d"], int)
    # last_off_duty_utc may be null until first completion.
    if data.get("last_off_duty_utc") is not None:
        assert is_iso8601_timestamp(data["last_off_duty_utc"])


def assert_pairing(data: dict) -> None:
    _assert_common_fields(data, "Pairing")
    assert data["state"] in VALID_PAIRING_STATES, (
        f"pairing state invalid: {data['state']!r}"
    )
    assert is_iso8601_timestamp(data["scheduled_start_utc"])
    assert is_iso8601_timestamp(data["scheduled_end_utc"])
    assert is_iso8601_timestamp(data["bidding_close_utc"])
    assert isinstance(data["required_captains"], int)
    assert isinstance(data["required_first_officers"], int)
    assert isinstance(data["required_cabin_crew"], int)
    assert isinstance(data["total_flight_minutes"], int)
    assert isinstance(data["total_duty_minutes"], int)
    assert isinstance(data["scheduled_block_minutes"], int)
    assert isinstance(data["actual_block_minutes"], int)


def assert_flight_leg(data: dict) -> None:
    _assert_common_fields(data, "FlightLeg")
    assert data["leg_type"] in VALID_LEG_TYPES
    assert is_iso8601_timestamp(data["scheduled_departure_utc"])
    assert is_iso8601_timestamp(data["scheduled_arrival_utc"])
    assert isinstance(data["flight_minutes"], int)


def assert_bid(data: dict) -> None:
    _assert_common_fields(data, "Bid")
    assert data["state"] in VALID_BID_STATES, f"bid state invalid: {data['state']!r}"
    assert data["requested_seat"] in VALID_SEATS


def assert_assignment(data: dict) -> None:
    _assert_common_fields(data, "Assignment")
    assert data["state"] in VALID_ASSIGNMENT_STATES, (
        f"assignment state invalid: {data['state']!r}"
    )
    assert data["source"] in VALID_ASSIGNMENT_SOURCES
    assert data["seat"] in VALID_SEATS
    if data.get("actual_duty_start_utc") is not None:
        assert is_iso8601_timestamp(data["actual_duty_start_utc"])
    if data.get("actual_duty_end_utc") is not None:
        assert is_iso8601_timestamp(data["actual_duty_end_utc"])


def assert_sick_call(data: dict) -> None:
    _assert_common_fields(data, "SickCall")
    assert data["state"] in VALID_SICK_CALL_STATES
    assert data["reason_code"] in VALID_SICK_REASON_CODES
    assert isinstance(data["hours_before_departure"], int)


def assert_reserve_callup(data: dict) -> None:
    _assert_common_fields(data, "ReserveCallup")
    assert data["state"] in VALID_RESERVE_CALLUP_STATES
    assert isinstance(data["callup_sequence"], int) and data["callup_sequence"] >= 1


def assert_trip_trade(data: dict) -> None:
    _assert_common_fields(data, "TripTrade")
    assert data["state"] in VALID_TRIP_TRADE_STATES


# ---------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------
def assert_version_advanced(before: dict, after: dict, by: int = 1) -> None:
    """Per PRD §2.4 every mutation advances version by exactly one."""
    assert after["version"] == before["version"] + by, (
        f"version must advance by {by}: before={before['version']}, "
        f"after={after['version']}"
    )
