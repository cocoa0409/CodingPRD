"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Primary resources carry id/created_at/updated_at/version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """ReleaseSignature and OperationalControlRecord carry only id and
    created_at; updated_at and version are absent (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not expose updated_at (PRD §2.5)"
    assert "version" not in data, "append-only record must not expose version (PRD §2.5)"


def assert_instant_equals(actual: str, expected_iso: str):
    """Compare two ISO 8601 instants by value, not by string format."""
    a = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    e = datetime.fromisoformat(expected_iso.replace("Z", "+00:00"))
    assert a == e, f"Expected instant {expected_iso}, got {actual}"


def assert_station(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["iata_code"], str) and data["iata_code"]
    assert isinstance(data["runway_length_m"], int)
    assert isinstance(data["alternate_distance_nm"], int)
    assert isinstance(data["min_ceiling_ft"], int)
    assert isinstance(data["min_visibility_m"], int)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_aircraft(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["tail_no"], str) and data["tail_no"]
    assert isinstance(data["type_code"], str) and data["type_code"]
    for f in ("oew_kg", "mzfw_kg", "mtow_kg", "mlw_kg", "fuel_capacity_kg",
              "cruise_tas_kts", "burn_kg_per_hour", "min_runway_m"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert isinstance(data["lemac_m"], (int, float))
    assert isinstance(data["mac_m"], (int, float))


def assert_dispatcher(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_no"], str) and data["license_no"]
    assert isinstance(data["max_active_legs"], int)
    assert isinstance(data["workload_leg_count"], int)
    assert isinstance(data["weighted_load_score"], int)


def assert_captain(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_no"], str) and data["license_no"]
    assert isinstance(data["qualified_type_codes"], list)


def assert_desk(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["region"], str)
    assert isinstance(data["max_dispatchers"], int)
    assert isinstance(data["active_shift_count"], int)
    assert isinstance(data["free_slots"], int)


def assert_desk_shift(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["dispatcher_id"])
    assert isinstance(data["shift_start_utc"], str)
    assert isinstance(data["shift_end_utc"], str)
    assert data["status"] in ("PLANNED", "ACTIVE", "ENDED")


def assert_leg(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["flight_no"], str) and data["flight_no"]
    for f in ("dep_station_id", "arr_station_id", "aircraft_id", "captain_id", "dispatcher_id"):
        assert is_valid_uuid(data[f]), f"{f} must reference an existing resource"
    assert isinstance(data["distance_nm"], int)
    assert data["ops_status"] in ("SCHEDULED", "DEPARTED", "ARRIVED", "DIVERTED", "CANCELLED")
    assert data["monitor_status"] in ("UNMONITORED", "MONITORING", "ALERTED", "CLOSED")
    assert isinstance(data["delay_count"], int)


def assert_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["leg_id"])
    assert isinstance(data["plan_seq"], int)
    assert data["wind_assumption"] in ("FORECAST", "WORST_CASE")
    assert data["status"] in ("COMPUTED", "LOCKED", "SUPERSEDED")
    for f in ("ground_speed_kts", "trip_time_min", "burn_eff_kg_per_hour", "trip_fuel_kg",
              "mel_fuel_penalty_kg", "contingency_kg", "alternate_fuel_kg",
              "final_reserve_kg", "required_fuel_kg"):
        assert isinstance(data[f], int), f"{f} must be an integer (PRD §2.7)"


def assert_manifest(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["leg_id"])
    assert is_valid_uuid(data["plan_id"])
    assert isinstance(data["pax_count"], int)
    assert isinstance(data["bags_count"], int)
    for f in ("pax_weight_kg", "baggage_kg", "cargo_billed_kg", "total_payload_kg",
              "zero_fuel_weight_kg", "takeoff_weight_kg", "landing_weight_kg",
              "max_payload_kg"):
        assert isinstance(data[f], int), f"{f} must be an integer (PRD §2.7)"
    assert isinstance(data["cg_percent_mac"], (int, float))


def assert_mel_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["aircraft_id"])
    assert data["category"] in ("MEL", "CDL")
    assert data["deferral_category"] in ("A", "B", "C", "D")
    assert data["status"] in ("OPEN", "CLEARED", "EXPIRED")


def assert_weather_package(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["ceiling_ft"], int)
    assert isinstance(data["visibility_m"], int)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_release(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["leg_id"])
    assert is_valid_uuid(data["plan_id"])
    assert is_valid_uuid(data["dispatcher_id"])
    assert is_valid_uuid(data["captain_id"])
    assert data["status"] in (
        "DRAFT", "PENDING_SIGNATURES", "RELEASED", "UNDER_AMENDMENT", "CANCELLED", "CLOSED",
    )
    assert isinstance(data["cycle_seq"], int)
    assert isinstance(data["amendment_count"], int)


def assert_release_signature(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["release_id"])
    assert data["signer_role"] in ("DISPATCHER", "CAPTAIN")
    assert isinstance(data["signer_id"], str) and data["signer_id"]
    assert isinstance(data["cycle_seq"], int)
    assert isinstance(data["signed_at_utc"], str)


def assert_control_record(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["leg_id"])
    assert data["actor_role"] in ("Dispatcher", "Captain", "DispatchSupervisor", "system")
    assert data["action"] in (
        "LEG_CREATED", "DELAY_DECISION", "CANCEL_DECISION", "DEPARTURE", "ARRIVAL",
        "DIVERSION", "RELEASE_CREATED", "RELEASE_SUBMITTED", "SIGNATURE_RECORDED",
        "RELEASE_RECALLED", "RELEASE_AMENDED", "RELEASE_AUTO_AMENDED",
        "DIVERT_RECOMMENDED", "MEL_EXPIRED",
    )


def assert_monitoring_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["leg_id"])
    assert isinstance(data["fuel_remaining_kg"], int)
    assert isinstance(data["projected_arrival_fuel_kg"], int)
    assert isinstance(data["fuel_margin_kg"], int)
    assert data["recommendation"] in ("NONE", "CONSIDER_DIVERT", "RECOMMEND_DIVERT")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED")


def assert_desk_quota_invariants(desk: dict):
    """Per-desk quota conservation: active_shift_count + free_slots ==
    max_dispatchers at every instant (PRD §3.1 free_slots definition)."""
    assert desk["active_shift_count"] + desk["free_slots"] == desk["max_dispatchers"], (
        f"quota not conserved: {desk['active_shift_count']} + {desk['free_slots']} "
        f"!= {desk['max_dispatchers']}"
    )
