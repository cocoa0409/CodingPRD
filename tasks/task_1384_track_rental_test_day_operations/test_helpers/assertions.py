"""Entity assertions and domain invariant checkers.

Structural assertions follow the PRD's identity rules: every resource carries
a server-minted UUID `id` and an ISO-8601 `created_at`; mutable resources also
carry `updated_at` and an integer `version`; waivers, safety inspections, and
noise readings are append-only and carry neither `updated_at` nor `version`.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_mutable_common(data: dict, entity: str):
    assert isinstance(data, dict), f"{entity} must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an integer >= 1"


def _assert_append_only_common(data: dict, entity: str):
    assert isinstance(data, dict), f"{entity} must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, f"{entity} is append-only: no updated_at"
    assert "version" not in data, f"{entity} is append-only: no version"


def assert_track(data: dict):
    _assert_mutable_common(data, "Track")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    for field in ("noise_limit_db", "run_group_capacity",
                  "garage_bay_count", "paddock_stall_count"):
        assert isinstance(data[field], int), f"Track.{field} must be an integer"


def assert_coach(data: dict):
    _assert_mutable_common(data, "Coach")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["cert_level"] in ("BASIC", "INTERMEDIATE", "RACE")
    assert isinstance(data["active"], bool)
    assert isinstance(data.get("assigned_booking_ids", []), list)


def assert_track_day(data: dict):
    _assert_mutable_common(data, "TrackDay")
    assert isinstance(data["date"], str) and len(data["date"]) == 10
    assert data["status"] in ("SCHEDULED", "OPEN", "WEATHER_HOLD", "RUNNING",
                              "STOPPED", "CLOSED", "CANCELLED")
    assert data["posture"] in ("NORMAL", "CAUTION", "SUSPENDED")
    assert data["weather_flag"] in ("CLEAR", "WATCH", "STOP")
    assert isinstance(data["open_incident_count"], int)
    assert isinstance(data["noise_breach_count"], int)
    assert isinstance(data["ops_run_index"], int)
    assert data.get("cancelled_reason") in (None, "CUSTOMER", "WEATHER", "SAFETY")


def assert_rental_block(data: dict):
    _assert_mutable_common(data, "RentalBlock")
    for field in ("block_index", "start_minute", "end_minute",
                  "max_group_size", "seats_reserved", "seats_available"):
        assert isinstance(data[field], int), f"RentalBlock.{field} must be an integer"
    assert data["status"] in ("OPEN", "FULL", "CLOSED")


def assert_booking(data: dict):
    _assert_mutable_common(data, "Booking")
    assert isinstance(data["organizer_user_id"], str)
    assert isinstance(data["group_name"], str)
    assert data["run_group_class"] in ("NOVICE", "INTERMEDIATE", "ADVANCED", "RACE")
    assert isinstance(data["driver_count"], int)
    assert data["approval_status"] in ("PENDING", "APPROVED", "REJECTED", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "AUTHORIZED", "CAPTURED",
                                      "REFUNDED", "FORFEITED")
    assert isinstance(data["refund_cents"], int)


def assert_driver(data: dict):
    _assert_mutable_common(data, "Driver")
    assert isinstance(data["full_name"], str)
    assert data["license_class"] in ("STREET", "CLUB", "PRO")
    assert data["waiver_status"] in ("PENDING", "SIGNED", "EXPIRED")
    assert data["safety_status"] in ("NOT_INSPECTED", "PASSED", "FAILED")
    assert isinstance(data["cleared_to_run"], bool)


def assert_waiver(data: dict):
    _assert_append_only_common(data, "Waiver")
    assert isinstance(data["driver_id"], str)
    assert is_iso8601_timestamp(data["signed_at_utc"])
    assert is_iso8601_timestamp(data["expires_at_utc"])
    assert isinstance(data["signature_payload_hash"], str)


def assert_safety_inspection(data: dict):
    _assert_append_only_common(data, "SafetyInspection")
    assert isinstance(data["driver_id"], str)
    assert isinstance(data["inspector_user_id"], str)
    assert isinstance(data["helmet_ok"], bool)
    assert isinstance(data["harness_ok"], bool)
    assert data["result"] in ("PASSED", "FAILED")
    assert is_iso8601_timestamp(data["inspected_at_utc"])


def assert_session(data: dict):
    _assert_mutable_common(data, "Session")
    assert data["run_group_class"] in ("NOVICE", "INTERMEDIATE", "ADVANCED", "RACE")
    assert data["status"] in ("GREEN", "RED", "BLACK", "CHECKERED")
    assert isinstance(data["lap_count"], int)
    assert isinstance(data["max_db_observed"], int)


def assert_incident(data: dict):
    _assert_mutable_common(data, "Incident")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["status"] in ("OPEN", "INVESTIGATING", "CLEARED")
    assert isinstance(data["reported_by_user_id"], str)


def assert_noise_reading(data: dict):
    _assert_append_only_common(data, "NoiseReading")
    assert isinstance(data["db_level"], int)
    assert is_iso8601_timestamp(data["recorded_at_utc"])
    assert isinstance(data["breach"], bool)


def assert_garage_assignment(data: dict):
    _assert_mutable_common(data, "GarageAssignment")
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["bay_number"], int)
    assert isinstance(data["power_hookups"], int)
    assert isinstance(data["water_hookup"], bool)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_paddock_assignment(data: dict):
    _assert_mutable_common(data, "PaddockAssignment")
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["stall_number"], int)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_block_seat_invariant(block: dict):
    """seats_reserved + seats_available must equal max_group_size on a live block."""
    assert block["seats_reserved"] + block["seats_available"] == block["max_group_size"], (
        f"Seat invariant broken: {block['seats_reserved']} + "
        f"{block['seats_available']} != {block['max_group_size']}"
    )
    assert block["seats_available"] >= 0, "seats_available is floored at zero"
