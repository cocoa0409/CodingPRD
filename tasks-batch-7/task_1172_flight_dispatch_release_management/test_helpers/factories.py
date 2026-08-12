"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import AIRCRAFT_A320, TEST_DEFAULTS

_COUNTER = {"n": 0}


def _seq() -> int:
    _COUNTER["n"] += 1
    return _COUNTER["n"]


def create_station_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "iata_code": f"KS{n:02d}",
        "runway_length_m": TEST_DEFAULTS["RUNWAY_M"],
        "alternate_distance_nm": 10,
        "min_ceiling_ft": TEST_DEFAULTS["STATION_MIN_CEILING_FT"],
        "min_visibility_m": TEST_DEFAULTS["STATION_MIN_VISIBILITY_M"],
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(**overrides) -> dict:
    defaults = dict(AIRCRAFT_A320)
    defaults["tail_no"] = f"N{100 + _seq()}T"
    defaults.update(overrides)
    return defaults


def create_dispatcher_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"name": f"Dana {n}", "license_no": f"D{n:03d}", "max_active_legs": 6}
    defaults.update(overrides)
    return defaults


def create_captain_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Cole {n}",
        "license_no": f"C{n:03d}",
        "qualified_type_codes": ["A320"],
    }
    defaults.update(overrides)
    return defaults


def create_desk_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"code": f"K{n}", "region": "WEST", "max_dispatchers": 1}
    defaults.update(overrides)
    return defaults


def create_desk_shift_payload(dispatcher_id: str, **overrides) -> dict:
    defaults = {
        "dispatcher_id": dispatcher_id,
        "shift_start_utc": TEST_DEFAULTS["SHIFT_START"],
        "shift_end_utc": TEST_DEFAULTS["SHIFT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_leg_payload(
    dep_station_id: str,
    arr_station_id: str,
    aircraft_id: str,
    captain_id: str,
    **overrides,
) -> dict:
    n = _seq()
    defaults = {
        "flight_no": f"FD{n:03d}",
        "dep_station_id": dep_station_id,
        "arr_station_id": arr_station_id,
        "aircraft_id": aircraft_id,
        "captain_id": captain_id,
        "distance_nm": TEST_DEFAULTS["LEG_DISTANCE_NM"],
        "sched_dep_utc": TEST_DEFAULTS["LEG_DEP"],
        "sched_arr_utc": TEST_DEFAULTS["LEG_ARR"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(leg_id: str, expected_leg_version: int, **overrides) -> dict:
    defaults = {
        "leg_id": leg_id,
        "route_code": TEST_DEFAULTS["ROUTE_CODE"],
        "cruise_altitude_ft": TEST_DEFAULTS["CRUISE_ALTITUDE_FT"],
        "forecast_wind_kts": TEST_DEFAULTS["FORECAST_WIND_KTS"],
        "wind_assumption": "FORECAST",
        "expected_leg_version": expected_leg_version,
    }
    defaults.update(overrides)
    return defaults


def create_manifest_payload(leg_id: str, **overrides) -> dict:
    defaults = {"leg_id": leg_id, "pax_count": 150, "bags_count": 150, "cargo_kg": 3000}
    defaults.update(overrides)
    return defaults


def create_mel_item_payload(aircraft_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "aircraft_id": aircraft_id,
        "item_code": f"25-{n}",
        "category": "MEL",
        "deferral_category": "C",
        "repair_deadline_utc": "2026-05-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_weather_package_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "valid_from_utc": TEST_DEFAULTS["WX_FROM"],
        "valid_to_utc": TEST_DEFAULTS["WX_TO"],
        "ceiling_ft": TEST_DEFAULTS["WX_CEILING_FT"],
        "visibility_m": TEST_DEFAULTS["WX_VISIBILITY_M"],
    }
    defaults.update(overrides)
    return defaults


def create_release_payload(leg_id: str, **overrides) -> dict:
    defaults = {"leg_id": leg_id}
    defaults.update(overrides)
    return defaults


def create_delay_payload(**overrides) -> dict:
    defaults = {
        "new_dep_utc": "2026-05-01T11:00:00Z",
        "new_arr_utc": "2026-05-01T13:30:00Z",
        "reason_code": "WX",
    }
    defaults.update(overrides)
    return defaults


def create_divert_payload(divert_station_id: str, **overrides) -> dict:
    defaults = {
        "divert_station_id": divert_station_id,
        "distance_nm": 90,
        "sched_dep_utc": "2026-05-01T10:35:00Z",
        "sched_arr_utc": "2026-05-01T11:30:00Z",
        "reason_code": "FUEL",
    }
    defaults.update(overrides)
    return defaults


def create_monitoring_event_payload(leg_id: str, **overrides) -> dict:
    defaults = {
        "leg_id": leg_id,
        "fuel_remaining_kg": 4595,
        "eta_destination_utc": TEST_DEFAULTS["EVENT_ETA"],
    }
    defaults.update(overrides)
    return defaults
