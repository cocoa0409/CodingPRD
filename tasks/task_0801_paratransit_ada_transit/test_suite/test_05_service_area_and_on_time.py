"""Three-quarter-mile service-area geometry and pickup-window on-time evaluation.

Queue A (Difficulty): boundary_precision_check (haversine boundary, pickup window).
Queue B (Corner): outside-service-area rejection, one-second-past-window not on-time.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_trip_payload, TEST_DEFAULTS,
)
import test_helpers as th

DRIVER = TEST_USERS["driver_headers"]
_D = TEST_DEFAULTS


# ==========================================================================
# Difficulty A — service-area haversine inclusive boundary (pickup accepted)
# ==========================================================================
def _request_boundary_pickup_trip(api):
    base = th.scenario_certified_rider_zone(api)
    za = base["zone_a"]["id"]
    payload = create_trip_payload(
        base["rider"]["id"], za, za,
        pickup_lat=_D["BOUNDARY_LAT_075_MI_NORTH"], pickup_lng=-74.0,
        dropoff_lat=40.0, dropoff_lng=-74.0)
    return api.create_trip(payload, th.make_rider_headers(base["rider"]["id"]))


def test_pickup_exactly_on_service_boundary_is_accepted(api):
    """PRD §2.7: "A location is inside the zone when the great-circle distance from the
    zone center to the location is less than or equal to `service_radius_miles`; a point
    lying exactly on the boundary is considered in-service."

    Design: Difficulty/boundary_precision_check/service_area_haversine_inclusive_boundary_pickup_accepted
    """
    resp = _request_boundary_pickup_trip(api)
    validate_success(resp, 201)


def test_boundary_pickup_trip_created_in_requested(api):
    """PRD §2.7: "Whenever a trip or subscription is created, both the pickup point and
    the dropoff point are checked against their respective zones' centers, and any point
    beyond its zone's radius rejects the request with `ERR_OUTSIDE_SERVICE_AREA`
    (HTTP 422)."
    PRD §3.4: "A successful request creates a `TripReservation` in `REQUESTED`."

    Design: Difficulty/boundary_precision_check/service_area_haversine_inclusive_boundary_pickup_accepted
    """
    resp = _request_boundary_pickup_trip(api)
    data = validate_success(resp, 201)
    assert data["status"] == "REQUESTED"


# ==========================================================================
# Difficulty A — pickup-window inclusive upper boundary is on-time
# ==========================================================================
def _pickup_at_window_edge(api):
    base = th.scenario_scheduled_trip(api, requested_pickup_at="2026-06-05T09:00:00Z")
    za = base["zone_a"]["id"]
    resp = api.pickup_trip(base["trip"]["id"],
                           {"actual_pickup_at": "2026-06-05T09:30:00Z", "actual_pickup_zone_id": za},
                           DRIVER)
    validate_success(resp, 200)
    return validate_success(api.get_trip(base["trip"]["id"], DRIVER))


def test_pickup_at_closing_edge_is_on_time(api):
    """PRD §3.8: "A pickup is on-time when the actual pickup instant falls within the
    pickup window, which opens at `scheduled_pickup_at` and closes 30 minutes later
    (`PICKUP_WINDOW_MINUTES`): `on_time` is true when the actual pickup is at or after the
    window start and at or before the window end, with both boundaries inclusive so that a
    pickup exactly at the closing edge is still on-time."

    Design: Difficulty/boundary_precision_check/pickup_window_inclusive_upper_boundary_is_on_time
    """
    trip = _pickup_at_window_edge(api)
    assert trip["on_time"] is True


def test_pickup_at_window_edge_transitions_to_picked_up(api):
    """PRD §3.8: "A driver records the actual pickup, supplying the `actual_pickup_at`
    instant and the `actual_pickup_zone_id`; this advances the trip from `SCHEDULED` or
    `EN_ROUTE` to `PICKED_UP` and computes the `on_time` flag."

    Design: Difficulty/boundary_precision_check/pickup_window_inclusive_upper_boundary_is_on_time
    """
    trip = _pickup_at_window_edge(api)
    assert trip["status"] == "PICKED_UP"


# ==========================================================================
# Corner B
# ==========================================================================
def test_trip_dropoff_outside_service_area_rejected(api):
    """PRD §2.7: "Whenever a trip or subscription is created, both the pickup point and
    the dropoff point are checked against their respective zones' centers, and any point
    beyond its zone's radius rejects the request with `ERR_OUTSIDE_SERVICE_AREA`
    (HTTP 422)."

    Design: Corner/calculations/trip_create_dropoff_outside_service_area_rejected
    """
    base = th.scenario_certified_rider_zone(api)
    za = base["zone_a"]["id"]
    payload = create_trip_payload(base["rider"]["id"], za, za,
                                  pickup_lat=40.0, pickup_lng=-74.0,
                                  dropoff_lat=_D["OUT_OF_AREA_LAT"], dropoff_lng=-74.0)
    resp = api.create_trip(payload, th.make_rider_headers(base["rider"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_SERVICE_AREA.value)


def test_pickup_one_second_past_window_not_on_time(api):
    """PRD §3.8: "`on_time` is true when the actual pickup is at or after the window start
    and at or before the window end, with both boundaries inclusive so that a pickup
    exactly at the closing edge is still on-time."

    Design: Corner/calculations/pickup_one_second_past_window_is_not_on_time
    """
    base = th.scenario_scheduled_trip(api, requested_pickup_at="2026-06-05T09:00:00Z")
    za = base["zone_a"]["id"]
    resp = api.pickup_trip(base["trip"]["id"],
                           {"actual_pickup_at": "2026-06-05T09:30:01Z", "actual_pickup_zone_id": za},
                           DRIVER)
    validate_success(resp, 200)
    trip = validate_success(api.get_trip(base["trip"]["id"], DRIVER))
    assert trip["on_time"] is False
    assert trip["status"] == "PICKED_UP"
