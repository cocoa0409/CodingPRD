"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface as
clear "setup failed" errors rather than confusing assertion failures.

Ownership note: a Rider's X-User-ID must equal the Rider.id, and a Driver's X-User-ID
must equal the Driver.id, for ownership-gated calls (request/cancel/dispute as the
rider; go-online/go-offline/start/complete/join/withdraw as the driver). Every helper
threads the real entity id through make_rider_headers(id) / make_driver_headers(id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_zone_payload,
    create_rider_payload,
    create_driver_payload,
    create_surge_snapshot_payload,
    create_trip_payload,
    create_airport_queue_payload,
    create_quest_payload,
    create_dispute_payload,
)
from .test_users import TEST_USERS, make_rider_headers, make_driver_headers

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── Tier 0: primitives ────────────────────────────────────────────────

def create_zone(grid_code="A1", base_fare_cents=1000, is_airport=False, name="Zone"):
    """Create a Zone. Returns the Zone dict (version 1, multiplier 1.00, COOL)."""
    payload = create_zone_payload(name=name, grid_code=grid_code,
                                  base_fare_cents=base_fare_cents, is_airport=is_airport)
    return get_success_data(api_client.create_zone(payload, DISPATCHER))


def get_zone(zone_id):
    return get_success_data(api_client.get_zone(zone_id, DISPATCHER))


def zone_version(zone_id):
    return get_zone(zone_id)["version"]


def create_rider(home_zone_id, wallet_balance_cents=0, name="Rider"):
    payload = create_rider_payload(home_zone_id, name=name,
                                   wallet_balance_cents=wallet_balance_cents)
    return get_success_data(api_client.create_rider(payload, DISPATCHER))


def create_driver(home_zone_id, name="Driver"):
    payload = create_driver_payload(home_zone_id, name=name)
    return get_success_data(api_client.create_driver(payload, DISPATCHER))


def go_online(driver_id):
    return get_success_data(api_client.go_online(driver_id, make_driver_headers(driver_id)))


def publish_snapshot(zone_id, observed_demand, observed_supply, is_rush_hour=False,
                     effective_from="2026-06-01T00:00:00Z",
                     effective_to="2026-06-01T01:00:00Z", expected_zone_version=None):
    """Publish a SurgeSnapshot. Reads the live zone version if not supplied."""
    if expected_zone_version is None:
        expected_zone_version = zone_version(zone_id)
    payload = create_surge_snapshot_payload(
        observed_demand=observed_demand, observed_supply=observed_supply,
        expected_zone_version=expected_zone_version, is_rush_hour=is_rush_hour,
        effective_from=effective_from, effective_to=effective_to)
    return get_success_data(api_client.create_surge_snapshot(zone_id, payload, DISPATCHER))


def request_trip(rider_id, pickup_zone_id, dropoff_zone_id):
    payload = create_trip_payload(rider_id, pickup_zone_id, dropoff_zone_id)
    return get_success_data(api_client.create_trip(payload, make_rider_headers(rider_id)))


def dispatch_tick(zone_id=None):
    payload = {"zone_id": zone_id} if zone_id else {}
    return get_success_data(api_client.dispatch_tick(payload, DISPATCHER))


# ─── Tier 1: Zone priced to a target multiplier ────────────────────────

def setup_zone_with_multiplier_2(grid_code="A1", base_fare_cents=1000,
                                 effective_to="2026-06-01T02:00:00Z"):
    """Zone whose current_multiplier is 2.00 (ratio 2.00, demand 4 / supply 2). Returns Zone."""
    z = create_zone(grid_code=grid_code, base_fare_cents=base_fare_cents)
    publish_snapshot(z["id"], observed_demand=4, observed_supply=2,
                     expected_zone_version=z["version"], effective_to=effective_to)
    return get_zone(z["id"])


# ─── Tier 2: a single online driver + funded rider in one zone ─────────

def setup_zone_rider_driver(grid_code="A1", base_fare_cents=1000, wallet_balance_cents=5000,
                            multiplier_2=False, effective_to="2026-06-01T02:00:00Z"):
    """Active scenario: one zone, one funded rider, one ONLINE (AVAILABLE) driver.

    If multiplier_2 is True the zone is priced to current_multiplier 2.00 BEFORE
    the driver goes online (snapshot publish happens first).
    Returns (zone, rider, driver) — all freshly re-read.
    """
    z = create_zone(grid_code=grid_code, base_fare_cents=base_fare_cents)
    if multiplier_2:
        publish_snapshot(z["id"], observed_demand=4, observed_supply=2,
                         expected_zone_version=z["version"], effective_to=effective_to)
    rider = create_rider(z["id"], wallet_balance_cents=wallet_balance_cents)
    driver = create_driver(z["id"])
    go_online(driver["id"])
    return get_zone(z["id"]), rider, get_success_data(
        api_client.get_driver(driver["id"], DISPATCHER))


# ─── Tier 3: trip lifecycle shortcuts ──────────────────────────────────

def setup_matched_trip(grid_code="A1", base_fare_cents=1000, wallet_balance_cents=5000,
                       multiplier_2=False, pickup_dropoff_same=True, dropoff_grid="B1",
                       effective_to="2026-06-01T02:00:00Z"):
    """Request a trip and run dispatch so it reaches MATCHED.

    Returns (zone, rider, driver, trip). When pickup_dropoff_same is False, a second
    dropoff zone is created and the returned zone is the PICKUP zone; the dropoff zone
    id is available on trip['dropoff_zone_id'].
    """
    z = create_zone(grid_code=grid_code, base_fare_cents=base_fare_cents)
    if multiplier_2:
        publish_snapshot(z["id"], observed_demand=4, observed_supply=2,
                         expected_zone_version=z["version"], effective_to=effective_to)
    rider = create_rider(z["id"], wallet_balance_cents=wallet_balance_cents)
    driver = create_driver(z["id"])
    go_online(driver["id"])
    if pickup_dropoff_same:
        dropoff_id = z["id"]
    else:
        dropoff_id = create_zone(grid_code=dropoff_grid, base_fare_cents=base_fare_cents,
                                 name="Dropoff")["id"]
    trip = request_trip(rider["id"], z["id"], dropoff_id)
    dispatch_tick(z["id"])
    trip = get_success_data(api_client.get_trip(trip["id"], DISPATCHER))
    return get_zone(z["id"]), rider, driver, trip


def setup_enroute_trip(grid_code="A1", base_fare_cents=1000, wallet_balance_cents=5000,
                       multiplier_2=False, pickup_dropoff_same=True, dropoff_grid="B1",
                       effective_to="2026-06-01T02:00:00Z"):
    """Drive a trip to ENROUTE. Returns (zone, rider, driver, trip)."""
    z, rider, driver, trip = setup_matched_trip(
        grid_code=grid_code, base_fare_cents=base_fare_cents,
        wallet_balance_cents=wallet_balance_cents, multiplier_2=multiplier_2,
        pickup_dropoff_same=pickup_dropoff_same, dropoff_grid=dropoff_grid,
        effective_to=effective_to)
    get_success_data(api_client.start_trip(trip["id"], make_driver_headers(driver["id"])))
    trip = get_success_data(api_client.get_trip(trip["id"], DISPATCHER))
    return z, rider, driver, trip


def setup_completed_trip(grid_code="A1", base_fare_cents=1000, wallet_balance_cents=5000,
                         multiplier_2=False, pickup_dropoff_same=True, dropoff_grid="B1",
                         effective_to="2026-06-01T02:00:00Z"):
    """Drive a trip all the way to COMPLETED. Returns (zone, rider, driver, trip)."""
    z, rider, driver, trip = setup_enroute_trip(
        grid_code=grid_code, base_fare_cents=base_fare_cents,
        wallet_balance_cents=wallet_balance_cents, multiplier_2=multiplier_2,
        pickup_dropoff_same=pickup_dropoff_same, dropoff_grid=dropoff_grid,
        effective_to=effective_to)
    get_success_data(api_client.complete_trip(trip["id"], make_driver_headers(driver["id"])))
    trip = get_success_data(api_client.get_trip(trip["id"], DISPATCHER))
    return z, rider, driver, trip


# ─── Tier 4: airport queue ─────────────────────────────────────────────

def setup_airport_zone(grid_code="Z9", base_fare_cents=1500):
    """Create an is_airport zone. Returns the Zone."""
    return create_zone(grid_code=grid_code, base_fare_cents=base_fare_cents,
                       is_airport=True, name="Airport")


def join_queue(zone_id, driver_id):
    payload = create_airport_queue_payload(zone_id, driver_id)
    return get_success_data(api_client.join_airport_queue(payload, make_driver_headers(driver_id)))


# ─── Tier 5: quests ────────────────────────────────────────────────────

def create_quest(driver_id, target_trips=3, bonus_cents=5000,
                 window_start="2026-06-01T10:00:00Z", window_end="2026-06-01T12:00:00Z"):
    payload = create_quest_payload(driver_id, target_trips=target_trips, bonus_cents=bonus_cents,
                                   window_start=window_start, window_end=window_end)
    return get_success_data(api_client.create_quest(payload, DISPATCHER))


# ─── Tier 6: disputes ──────────────────────────────────────────────────

def open_dispute(rider_id, trip_id, reason="OVERCHARGED", requested_refund_cents=500):
    payload = create_dispute_payload(trip_id, reason=reason,
                                     requested_refund_cents=requested_refund_cents)
    return get_success_data(api_client.create_dispute(payload, make_rider_headers(rider_id)))


def resolve_dispute(dispute_id, decision):
    return get_success_data(
        api_client.resolve_dispute(dispute_id, {"decision": decision}, DISPATCHER))
