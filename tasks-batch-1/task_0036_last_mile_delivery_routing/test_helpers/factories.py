"""Payload factories — one per entity, input fields only."""
import uuid


def _unique_code(prefix="TC"):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def create_transit_center_payload(**overrides) -> dict:
    defaults = {"name": "Test Hub", "sort_capacity": 10}
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    defaults = {"name": "Test Driver", "vehicle_capacity_kg": 50.0}
    defaults.update(overrides)
    return defaults


def create_parcel_payload(**overrides) -> dict:
    defaults = {"tracking_code": _unique_code("P"), "weight_kg": 1.0}
    defaults.update(overrides)
    return defaults


def create_route_payload(driver_id, origin_center_id, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "origin_center_id": origin_center_id,
        "service_date": "2026-06-01",
        "max_stops": 5,
    }
    defaults.update(overrides)
    return defaults


def create_stop_payload(route_id, parcel_id, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "parcel_id": parcel_id,
        "sequence": 1,
        "window_start_min": 540,
        "window_end_min": 600,
    }
    defaults.update(overrides)
    return defaults


def create_attempt_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_appointment_payload(stop_id, **overrides) -> dict:
    defaults = {
        "stop_id": stop_id,
        "requested_start_min": 700,
        "requested_end_min": 760,
    }
    defaults.update(overrides)
    return defaults
