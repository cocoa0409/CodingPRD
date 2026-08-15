"""Payload factories — one per creatable entity, input fields only.

Computed and system-managed fields (pricing triple, statuses, pins,
counters, audit user ids, timestamps) are never part of a request body.
"""
from .constants import (
    DEFAULT_AUTH_WINDOW_END,
    DEFAULT_AUTH_WINDOW_START,
    DEFAULT_READING_AT,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)

DEFAULTS = {
    "SITE_NAME": "Site A",
    "LATITUDE": 34.0,
    "LONGITUDE": -118.0,
    "GROUND_LENGTH_M": 1000,
    "GROUND_WIDTH_M": 800,
    "SITE_MAX_WIND_KT": 20,
    "SITE_MAX_GUST_KT": 25,
    "SITE_MAX_ALTITUDE_FT": 500,
    "SHOW_NAME": "Show S",
    "DRONE_COUNT_PLANNED": 10,
    "DESIGN_DRONE_COUNT": 10,
    "DESIGN_MAX_ALTITUDE_FT": 300,
    "DESIGN_DURATION_SEC": 600,
    "DESIGN_MIN_SEPARATION_M": 3.0,
    "SIM_MIN_SEPARATION_OBSERVED_M": 3.5,
    "SIM_BATTERY_DRAW_PCT": 55,
    "SIM_MAX_SPEED_MPS": 9.0,
    "CONFIG_GEOFENCE_RADIUS_M": 250,
    "CONFIG_ALTITUDE_HARD_CEILING_FT": 400,
    "CONFIG_LOST_LINK_ACTION": "RETURN_TO_HOME",
    "CONFIG_GEOFENCE_BREACH_ACTION": "IMMEDIATE_LAND",
    "CONFIG_BATTERY_RTL_THRESHOLD_PCT": 30,
    "AUTH_ALTITUDE_CEILING_FT": 450,
    "DRONE_MODEL": "LUM-2",
    "BAY_CODE": "BAY-1",
    "BAY_PORT_COUNT": 2,
    "WEATHER_WIND_SPEED_KT": 8,
    "WEATHER_GUST_KT": 11,
    "WEATHER_PRECIP_MM_HR": 0.0,
    "WEATHER_TEMPERATURE_C": 18,
    "FLIGHT_BATTERY_CONSUMED_PCT": 30,
    "FLIGHT_MAX_ALTITUDE_REACHED_FT": 195,
    "FLIGHT_MAX_DEVIATION_M": 1.0,
}


def create_site_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SITE_NAME"],
        "latitude": DEFAULTS["LATITUDE"],
        "longitude": DEFAULTS["LONGITUDE"],
        "ground_length_m": DEFAULTS["GROUND_LENGTH_M"],
        "ground_width_m": DEFAULTS["GROUND_WIDTH_M"],
        "site_max_wind_kt": DEFAULTS["SITE_MAX_WIND_KT"],
        "site_max_gust_kt": DEFAULTS["SITE_MAX_GUST_KT"],
        "site_max_altitude_ft": DEFAULTS["SITE_MAX_ALTITUDE_FT"],
    }
    payload.update(overrides)
    return payload


def create_show_event_payload(site_id, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "name": DEFAULTS["SHOW_NAME"],
        "window_start": DEFAULT_WINDOW_START,
        "window_end": DEFAULT_WINDOW_END,
        "drone_count_planned": DEFAULTS["DRONE_COUNT_PLANNED"],
    }
    payload.update(overrides)
    return payload


def create_show_design_payload(show_event_id, **overrides) -> dict:
    payload = {
        "show_event_id": show_event_id,
        "drone_count": DEFAULTS["DESIGN_DRONE_COUNT"],
        "max_altitude_ft": DEFAULTS["DESIGN_MAX_ALTITUDE_FT"],
        "duration_sec": DEFAULTS["DESIGN_DURATION_SEC"],
        "min_separation_m": DEFAULTS["DESIGN_MIN_SEPARATION_M"],
    }
    payload.update(overrides)
    return payload


def create_simulation_run_payload(show_design_id, **overrides) -> dict:
    payload = {
        "show_design_id": show_design_id,
        "min_separation_observed_m": DEFAULTS["SIM_MIN_SEPARATION_OBSERVED_M"],
        "battery_draw_pct": DEFAULTS["SIM_BATTERY_DRAW_PCT"],
        "max_speed_mps": DEFAULTS["SIM_MAX_SPEED_MPS"],
    }
    payload.update(overrides)
    return payload


def create_safety_configuration_payload(show_event_id, expected_show_event_version,
                                        **overrides) -> dict:
    payload = {
        "show_event_id": show_event_id,
        "geofence_radius_m": DEFAULTS["CONFIG_GEOFENCE_RADIUS_M"],
        "altitude_hard_ceiling_ft": DEFAULTS["CONFIG_ALTITUDE_HARD_CEILING_FT"],
        "lost_link_action": DEFAULTS["CONFIG_LOST_LINK_ACTION"],
        "geofence_breach_action": DEFAULTS["CONFIG_GEOFENCE_BREACH_ACTION"],
        "battery_rtl_threshold_pct": DEFAULTS["CONFIG_BATTERY_RTL_THRESHOLD_PCT"],
        "expected_show_event_version": expected_show_event_version,
    }
    payload.update(overrides)
    return payload


def create_authorization_payload(show_event_id, **overrides) -> dict:
    payload = {
        "show_event_id": show_event_id,
        "window_start": DEFAULT_AUTH_WINDOW_START,
        "window_end": DEFAULT_AUTH_WINDOW_END,
        "altitude_ceiling_ft": DEFAULTS["AUTH_ALTITUDE_CEILING_FT"],
        "waiver_types": [],
    }
    payload.update(overrides)
    return payload


def create_drone_payload(serial_number, **overrides) -> dict:
    payload = {
        "serial_number": serial_number,
        "model": DEFAULTS["DRONE_MODEL"],
    }
    payload.update(overrides)
    return payload


def create_charge_bay_payload(site_id, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "bay_code": DEFAULTS["BAY_CODE"],
        "port_count": DEFAULTS["BAY_PORT_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_charge_session_payload(drone_id, charge_bay_id, **overrides) -> dict:
    payload = {
        "drone_id": drone_id,
        "charge_bay_id": charge_bay_id,
    }
    payload.update(overrides)
    return payload


def create_launch_grid_assignment_payload(show_event_id, drone_id, grid_row,
                                          grid_col, **overrides) -> dict:
    payload = {
        "show_event_id": show_event_id,
        "drone_id": drone_id,
        "grid_row": grid_row,
        "grid_col": grid_col,
    }
    payload.update(overrides)
    return payload


def create_weather_reading_payload(site_id, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "recorded_at": DEFAULT_READING_AT,
        "wind_speed_kt": DEFAULTS["WEATHER_WIND_SPEED_KT"],
        "gust_kt": DEFAULTS["WEATHER_GUST_KT"],
        "precip_mm_hr": DEFAULTS["WEATHER_PRECIP_MM_HR"],
        "temperature_c": DEFAULTS["WEATHER_TEMPERATURE_C"],
    }
    payload.update(overrides)
    return payload


def create_go_no_go_evaluation_payload(show_event_id, **overrides) -> dict:
    payload = {
        "show_event_id": show_event_id,
    }
    payload.update(overrides)
    return payload


def create_incident_report_payload(show_event_id, **overrides) -> dict:
    payload = {
        "show_event_id": show_event_id,
        "severity": "MINOR",
        "description": "Test incident report",
    }
    payload.update(overrides)
    return payload


def create_flight_log_payload(show_event_id, drone_id, **overrides) -> dict:
    payload = {
        "show_event_id": show_event_id,
        "drone_id": drone_id,
        "battery_consumed_pct": DEFAULTS["FLIGHT_BATTERY_CONSUMED_PCT"],
        "max_altitude_reached_ft": DEFAULTS["FLIGHT_MAX_ALTITUDE_REACHED_FT"],
        "max_deviation_m": DEFAULTS["FLIGHT_MAX_DEVIATION_M"],
    }
    payload.update(overrides)
    return payload
