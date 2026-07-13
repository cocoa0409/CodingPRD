"""Standing (subscription) trips: creation and dispatcher instantiation.

Queue B (Corner): entities / subscription creation and instantiation side effect.
"""
from test_helpers import validate_success, TEST_USERS, create_subscription_payload
import test_helpers as th

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_subscription_created_active(api):
    """PRD §3.4: "A standing subscription is created as a `SubscriptionTrip` template for
    a rider, supplying the `rider_id`, `pickup_zone_id`, `dropoff_zone_id`, the standing
    coordinates `pickup_lat`, `pickup_lng`, `dropoff_lat`, and `dropoff_lng`, a recurring
    `day_of_week` (one of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, or `SUN`), and a
    recurring `pickup_time_utc` expressed as `HH:MM` in UTC."
    PRD §3.4: "A subscription is created with `status` `ACTIVE` and may later be
    `CANCELLED`."

    Design: Corner/entities/subscription_trip_creation_active
    """
    base = th.scenario_certified_rider_zone(api)
    rider_id = base["rider"]["id"]
    za = base["zone_a"]["id"]
    payload = create_subscription_payload(rider_id, za, za, day_of_week="FRI", pickup_time_utc="09:00")
    resp = api.create_subscription(payload, th.make_rider_headers(rider_id))
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["day_of_week"] == "FRI"


def test_instantiate_subscription_creates_linked_trip(api):
    """PRD §3.4: "The dispatcher supplies the `service_date` and the `requested_pickup_at`
    for the instance, and the system creates a `TripReservation` in `REQUESTED` with its
    `subscription_trip_id` set to the originating subscription."

    Design: Corner/entities/subscription_instantiate_creates_trip_reservation
    """
    base = th.scenario_certified_rider_zone(api)
    rider_id = base["rider"]["id"]
    za = base["zone_a"]["id"]
    sub = validate_success(api.create_subscription(
        create_subscription_payload(rider_id, za, za), th.make_rider_headers(rider_id)), 201)
    resp = api.instantiate_subscription(
        sub["id"], {"service_date": "2026-06-05", "requested_pickup_at": "2026-06-05T09:00:00Z"},
        DISPATCHER)
    trip = validate_success(resp, 201)
    assert trip["status"] == "REQUESTED"
    assert trip["subscription_trip_id"] == sub["id"]
