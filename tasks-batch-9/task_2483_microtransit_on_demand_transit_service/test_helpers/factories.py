"""Payload factories — one per resource, carrying only the fields a client supplies."""

from .constants import TEST_DEFAULTS


def service_zone_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["ZONE_NAME"],
        "zone_code": TEST_DEFAULTS["ZONE_CODE"],
        "max_walk_meters": TEST_DEFAULTS["MAX_WALK_METERS"],
        "detour_tolerance_pct": TEST_DEFAULTS["DETOUR_TOLERANCE_PCT"],
        "detour_tolerance_floor_minutes": TEST_DEFAULTS[
            "DETOUR_TOLERANCE_FLOOR_MINUTES"
        ],
        "base_fare_cents": TEST_DEFAULTS["BASE_FARE_CENTS"],
        "fare_cap_cents_daily": TEST_DEFAULTS["FARE_CAP_CENTS_DAILY"],
        "fare_cap_cents_weekly": TEST_DEFAULTS["FARE_CAP_CENTS_WEEKLY"],
        "on_time_window_minutes": TEST_DEFAULTS["ON_TIME_WINDOW_MINUTES"],
        "curb_capacity_per_bucket": TEST_DEFAULTS["CURB_CAPACITY_PER_BUCKET"],
    }
    payload.update(overrides)
    return payload


def virtual_stop_payload(zone_id, stop_code, corridor_index, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "stop_code": stop_code,
        "corridor_index": corridor_index,
        "walk_shed_meters": TEST_DEFAULTS["WALK_SHED_METERS"],
        "accessibility": "ACCESSIBLE_PATH",
    }
    payload.update(overrides)
    return payload


def transit_connection_payload(zone_id, stop_id, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "stop_id": stop_id,
        "mode": "RAIL",
        "route_code": "ORANGE-IB",
        "scheduled_departure_utc": "2026-08-03T07:00:00Z",
        "guaranteed_transfer_buffer_minutes": 10,
        "transfer_credit_cents": 80,
    }
    payload.update(overrides)
    return payload


def vehicle_payload(zone_id, vehicle_code, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "vehicle_code": vehicle_code,
        "seat_capacity": TEST_DEFAULTS["SEAT_CAPACITY"],
        "wav_positions": TEST_DEFAULTS["WAV_POSITIONS"],
    }
    payload.update(overrides)
    return payload


def driver_payload(zone_id, driver_code, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "driver_code": driver_code,
        "wav_certified": True,
    }
    payload.update(overrides)
    return payload


def rider_payload(zone_id, rider_code, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "rider_code": rider_code,
        "fare_category": "FULL",
        "mobility_device": "NONE",
    }
    payload.update(overrides)
    return payload


def demand_forecast_payload(zone_id, zone_version, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "window_start_utc": TEST_DEFAULTS["BLOCK_START_UTC"],
        "window_end_utc": TEST_DEFAULTS["BLOCK_END_UTC"],
        "forecast_trips": 10,
        "peak_factor": 1.20,
        "expected_service_zone_version": zone_version,
    }
    payload.update(overrides)
    return payload


def vehicle_block_payload(zone_id, vehicle_id, driver_id, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "vehicle_id": vehicle_id,
        "driver_id": driver_id,
        "block_type": "BASE",
        "start_utc": TEST_DEFAULTS["BLOCK_START_UTC"],
        "end_utc": TEST_DEFAULTS["BLOCK_END_UTC"],
    }
    payload.update(overrides)
    return payload


def trip_request_payload(
    zone_id, rider_id, origin_stop_id, destination_stop_id, **overrides
) -> dict:
    payload = {
        "zone_id": zone_id,
        "rider_id": rider_id,
        "origin_stop_id": origin_stop_id,
        "destination_stop_id": destination_stop_id,
        "requested_pickup_utc": TEST_DEFAULTS["REQUESTED_PICKUP_UTC"],
        "party_size": 1,
    }
    payload.update(overrides)
    return payload


def pool_assignment_payload(
    trip_request_id, block_id, expected_vehicle_block_version, **overrides
) -> dict:
    payload = {
        "trip_request_id": trip_request_id,
        "block_id": block_id,
        "expected_vehicle_block_version": expected_vehicle_block_version,
    }
    payload.update(overrides)
    return payload


def subsidy_report_payload(zone_id, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "period_start_date": "2026-08-03",
        "period_end_date": "2026-08-03",
        "variant": "PROVISIONAL",
    }
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
