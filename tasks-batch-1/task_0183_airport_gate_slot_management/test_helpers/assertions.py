"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id/created_at/updated_at/version present on every versioned resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_gate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["terminal"], str)
    assert isinstance(data["max_wingspan_m"], (int, float)) and data["max_wingspan_m"] >= 0
    assert isinstance(data["is_cute_equipped"], bool)
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")
    assert isinstance(data["active_assignment_count"], int) and data["active_assignment_count"] >= 0


def assert_remote_stand(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["max_wingspan_m"], (int, float)) and data["max_wingspan_m"] >= 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["status"] == "ACTIVE"
    assert isinstance(data["occupancy_count"], int) and data["occupancy_count"] >= 0


def assert_cute_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["terminal"], str)
    assert data["status"] == "AVAILABLE"


def assert_ground_equipment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["asset_tag"], str) and len(data["asset_tag"]) > 0
    assert data["equipment_type"] in ("GPU", "PUSHBACK_TUG", "BELT_LOADER", "AIR_START")
    assert isinstance(data["turnaround_minutes"], int) and data["turnaround_minutes"] >= 0
    assert data["status"] == "AVAILABLE"


def assert_flight(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["flight_no"], str) and len(data["flight_no"]) > 0
    assert isinstance(data["aircraft_wingspan_m"], (int, float)) and data["aircraft_wingspan_m"] >= 0
    assert isinstance(data["sched_departure_utc"], str)
    assert isinstance(data["min_turn_minutes"], int) and data["min_turn_minutes"] >= 0
    assert data["schedule_status"] in ("SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED", "DIVERTED")
    assert data["handling_status"] in ("UNASSIGNED", "ASSIGNED", "AT_GATE", "TOWED_OFF", "DEPARTED")


def assert_slot_permit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("flight_id", "")), "flight_id must be a valid UUID"
    assert data["movement_type"] in ("ARRIVAL", "DEPARTURE")
    assert isinstance(data["slot_time_utc"], str)
    assert isinstance(data["tolerance_minutes"], int) and data["tolerance_minutes"] >= 0
    assert data["status"] in ("REQUESTED", "CONFIRMED", "USED", "FORFEITED", "CANCELLED")


def assert_gate_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("flight_id", "")), "flight_id must be a valid UUID"
    assert data["stand_type"] in ("GATE", "REMOTE")
    assert isinstance(data["start_utc"], str)
    assert isinstance(data["end_utc"], str)
    assert data["status"] in ("PLANNED", "OCCUPIED", "TOWED_AWAY", "RELEASED", "CANCELLED")
    assert isinstance(data["occupancy_minutes"], int)


def assert_cute_allocation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("flight_id", "")), "flight_id must be a valid UUID"
    assert is_valid_uuid(data.get("cute_unit_id", "")), "cute_unit_id must be a valid UUID"
    assert data["status"] in ("HELD", "RELEASED", "CANCELLED")


def assert_gse_allocation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("flight_id", "")), "flight_id must be a valid UUID"
    assert is_valid_uuid(data.get("equipment_id", "")), "equipment_id must be a valid UUID"
    assert data["status"] in ("HELD", "RELEASED", "CANCELLED")
