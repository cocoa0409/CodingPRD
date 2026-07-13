"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_service_area_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["SA_NAME"],
        "center_lat": TEST_DEFAULTS["SA_CENTER_LAT"],
        "center_lon": TEST_DEFAULTS["SA_CENTER_LON"],
        "max_range_km": TEST_DEFAULTS["SA_MAX_RANGE_KM"],
        "max_payload_g": TEST_DEFAULTS["SA_MAX_PAYLOAD_G"],
    }
    payload.update(overrides)
    return payload


def create_nest_payload(service_area_id: str, **overrides) -> dict:
    payload = {
        "service_area_id": service_area_id,
        "name": TEST_DEFAULTS["NEST_NAME"],
        "lat": TEST_DEFAULTS["NEST_LAT"],
        "lon": TEST_DEFAULTS["NEST_LON"],
        "pad_count": TEST_DEFAULTS["NEST_PAD_COUNT"],
        "status": "OPEN",
    }
    payload.update(overrides)
    return payload


def create_drone_payload(home_nest_id: str, **overrides) -> dict:
    payload = {
        "home_nest_id": home_nest_id,
        "tail_number": TEST_DEFAULTS["TAIL_NUMBER"],
        "airframe_class": TEST_DEFAULTS["AIRFRAME_CLASS"],
        "max_payload_g": TEST_DEFAULTS["DRONE_MAX_PAYLOAD_G"],
        "cruise_speed_kmh": TEST_DEFAULTS["CRUISE_SPEED_KMH"],
        "hours_since_service": TEST_DEFAULTS["HOURS_SINCE_SERVICE"],
    }
    payload.update(overrides)
    return payload


def create_battery_payload(nest_id: str, **overrides) -> dict:
    payload = {
        "nest_id": nest_id,
        "serial": TEST_DEFAULTS["BATTERY_SERIAL"],
        "charge_pct": TEST_DEFAULTS["BATTERY_CHARGE_PCT"],
        "cycle_count": TEST_DEFAULTS["BATTERY_CYCLE_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["CUSTOMER_NAME"],
        "email": TEST_DEFAULTS["CUSTOMER_EMAIL"],
        "dropoff_lat": TEST_DEFAULTS["DROPOFF_LAT"],
        "dropoff_lon": TEST_DEFAULTS["DROPOFF_LON"],
    }
    payload.update(overrides)
    return payload


def create_order_payload(customer_id: str, service_area_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "service_area_id": service_area_id,
        "payload_weight_g": TEST_DEFAULTS["PAYLOAD_WEIGHT_G"],
        "priority": "STANDARD",
    }
    payload.update(overrides)
    return payload


def dispatch_order_payload(nest_id: str, expected_order_version: int, **overrides) -> dict:
    payload = {"nest_id": nest_id, "expected_order_version": expected_order_version}
    payload.update(overrides)
    return payload


def file_authorization_payload(**overrides) -> dict:
    payload = {
        "grid_cells": list(TEST_DEFAULTS["GRID_CELLS"]),
        "requested_alt_ft": TEST_DEFAULTS["REQUESTED_ALT_FT"],
        "window_start": TEST_DEFAULTS["WINDOW_START"],
        "window_end": TEST_DEFAULTS["WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def drop_payload(**overrides) -> dict:
    payload = {
        "hover_alt_ft": TEST_DEFAULTS["HOVER_ALT_FT"],
        "photo_ref": TEST_DEFAULTS["PHOTO_REF"],
    }
    payload.update(overrides)
    return payload


def create_geofence_zone_payload(service_area_id: str, **overrides) -> dict:
    payload = {
        "service_area_id": service_area_id,
        "kind": "NO_FLY",
        "center_lat": TEST_DEFAULTS["DROPOFF_LAT"],
        "center_lon": TEST_DEFAULTS["DROPOFF_LON"],
        "radius_km": 1.0,
        "effective_from": "2026-06-01T08:00:00Z",
        "effective_to": "2026-06-01T18:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_weather_observation_payload(service_area_id: str, **overrides) -> dict:
    payload = {
        "service_area_id": service_area_id,
        "observed_at": "2026-06-01T08:30:00Z",
        "wind_kph": 5,
        "gust_kph": 10,
        "visibility_km": 8,
        "precip": "NONE",
    }
    payload.update(overrides)
    return payload


def create_incident_payload(drone_id: str, **overrides) -> dict:
    payload = {
        "drone_id": drone_id,
        "severity": "MINOR",
        "category": "HARD_LANDING",
        "narrative": "Firm touchdown on the pad",
    }
    payload.update(overrides)
    return payload


def create_maintenance_log_payload(
    drone_id: str, expected_drone_version: int, **overrides
) -> dict:
    payload = {
        "drone_id": drone_id,
        "work_type": "INSPECTION",
        "scheduled_start": "2026-06-02T10:00:00Z",
        "scheduled_end": "2026-06-02T12:00:00Z",
        "expected_drone_version": expected_drone_version,
        "notes": "routine",
    }
    payload.update(overrides)
    return payload
