"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

_D = TEST_DEFAULTS


def create_rider_payload(**overrides) -> dict:
    """Required: full_name, phone, email, home_lat, home_lng.
    Optional: mobility_device (default NONE), requires_pca (default false)."""
    payload = {
        "full_name": "Test Rider",
        "phone": "555-0100",
        "email": "rider@example.com",
        "home_lat": _D["ZA_CENTER_LAT"],
        "home_lng": _D["ZA_CENTER_LNG"],
    }
    payload.update(overrides)
    return payload


def create_service_zone_payload(**overrides) -> dict:
    """Required: zone_code, name, center_lat, center_lng, base_fare_cents,
    fixed_route_fare_cents. Optional: service_radius_miles (default 0.75)."""
    payload = {
        "zone_code": "ZA",
        "name": "Zone A",
        "center_lat": _D["ZA_CENTER_LAT"],
        "center_lng": _D["ZA_CENTER_LNG"],
        "service_radius_miles": 0.75,
        "base_fare_cents": _D["ZA_BASE_FARE_CENTS"],
        "fixed_route_fare_cents": _D["ZA_FIXED_ROUTE_FARE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_application_payload(rider_id, **overrides) -> dict:
    """Required: rider_id. Optional: application_type (default NEW)."""
    payload = {"rider_id": rider_id}
    payload.update(overrides)
    return payload


def create_assessment_payload(application_id, scheduled_at="2026-06-02T10:00:00Z", **overrides) -> dict:
    payload = {"application_id": application_id, "scheduled_at": scheduled_at}
    payload.update(overrides)
    return payload


def complete_assessment_payload(outcome="PASS_UNCONDITIONAL", assessed_mobility_device="NONE", **overrides) -> dict:
    payload = {"outcome": outcome, "assessed_mobility_device": assessed_mobility_device}
    payload.update(overrides)
    return payload


def create_trip_payload(rider_id, pickup_zone_id, dropoff_zone_id,
                        requested_pickup_at="2026-06-05T09:00:00Z", **overrides) -> dict:
    """Ad-hoc trip request. Coordinates default to the ZA center (in-service)."""
    payload = {
        "rider_id": rider_id,
        "pickup_zone_id": pickup_zone_id,
        "dropoff_zone_id": dropoff_zone_id,
        "pickup_lat": _D["ZA_CENTER_LAT"],
        "pickup_lng": _D["ZA_CENTER_LNG"],
        "dropoff_lat": _D["ZA_CENTER_LAT"],
        "dropoff_lng": _D["ZA_CENTER_LNG"],
        "requested_pickup_at": requested_pickup_at,
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(rider_id, pickup_zone_id, dropoff_zone_id,
                                day_of_week="FRI", pickup_time_utc="09:00", **overrides) -> dict:
    payload = {
        "rider_id": rider_id,
        "pickup_zone_id": pickup_zone_id,
        "dropoff_zone_id": dropoff_zone_id,
        "pickup_lat": _D["ZA_CENTER_LAT"],
        "pickup_lng": _D["ZA_CENTER_LNG"],
        "dropoff_lat": _D["ZA_CENTER_LAT"],
        "dropoff_lng": _D["ZA_CENTER_LNG"],
        "day_of_week": day_of_week,
        "pickup_time_utc": pickup_time_utc,
    }
    payload.update(overrides)
    return payload


def create_run_payload(service_zone_id, service_date="2026-06-05",
                       total_ambulatory_seats=4, total_wheelchair_positions=2, **overrides) -> dict:
    payload = {
        "service_zone_id": service_zone_id,
        "service_date": service_date,
        "total_ambulatory_seats": total_ambulatory_seats,
        "total_wheelchair_positions": total_wheelchair_positions,
    }
    payload.update(overrides)
    return payload
