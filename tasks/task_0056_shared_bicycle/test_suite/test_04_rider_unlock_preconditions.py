"""Unlock preconditions: bike state, geofence, rider eligibility, wallet.

PRD §3.4 enumerates the unlock preconditions and the validation
priority for each error. PRD §3.3 enumerates rider-side state and the
minimum unlock balance.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    create_bike,
    create_funded_rider,
    create_geofence,
    create_region,
    create_rider,
    create_ride_payload,
    get_bike,
    get_region,
    get_rider,
    make_rider_headers,
    make_square_polygon,
    recall_bike,
    setup_basic_ride_scenario,
    setup_region_with_bikes,
    setup_region_with_forbidden_zone,
    setup_rider_with_monthly_pass,
    shelf_bike_on,
    start_ride,
    validate_error,
    validate_success,
    ADMIN,
    OPERATOR,
)


class TestUnlockBikeState:
    def test_bike_off_shelf_rejected(self, api):
        """PRD §3.4: 'The bike must be ON_SHELF — otherwise
        ERR_BIKE_OFF_SHELF.'"""
        bike = create_bike(model="STANDARD")
        rider = create_funded_rider()
        resp = api.create_ride(
            create_ride_payload(rider_id=rider["id"], bike_id=bike["id"]),
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BIKE_OFF_SHELF.value, 409)

    def test_bike_not_available_rejected_when_in_use(self, api):
        """PRD §3.4: 'The bike's status must be AVAILABLE — otherwise
        ERR_BIKE_NOT_AVAILABLE.'"""
        ctx = setup_basic_ride_scenario()
        start_ride(ctx["rider"], ctx["bike"])
        # Try a second rider on the same bike
        rider2 = create_funded_rider()
        resp = api.create_ride(
            create_ride_payload(rider_id=rider2["id"],
                                bike_id=ctx["bike"]["id"]),
            make_rider_headers(rider2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BIKE_NOT_AVAILABLE.value, 409)

    def test_bike_recall_rejected(self, api):
        """PRD §3.4: 'The bike's status must be AVAILABLE — otherwise
        ERR_BIKE_NOT_AVAILABLE.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        recall_bike(bikes[0]["id"])
        rider = create_funded_rider()
        resp = api.create_ride(
            create_ride_payload(rider_id=rider["id"], bike_id=bikes[0]["id"]),
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BIKE_NOT_AVAILABLE.value, 409)


class TestUnlockGeofence:
    def test_unlock_inside_forbidden_zone_rejected(self, api):
        """PRD §3.4: 'The bike's current location must not fall inside
        any FORBIDDEN active Geofence in its region_id — otherwise
        ERR_BIKE_IN_FORBIDDEN_ZONE.'"""
        # Build a region with a forbidden zone, then patch the bike's
        # last_lat/last_lng inside that polygon.
        ctx = setup_region_with_forbidden_zone(
            center_lat=30.5, center_lng=120.5, side=0.01, num_bikes=1,
        )
        # PATCH bike location to inside the forbidden polygon.
        bike = ctx["bikes"][0]
        from test_helpers import patch_bike
        patch_bike(bike["id"],
                   last_lat=ctx["forbidden_lat"],
                   last_lng=ctx["forbidden_lng"])
        rider = create_funded_rider()
        resp = api.create_ride(
            create_ride_payload(rider_id=rider["id"], bike_id=bike["id"]),
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BIKE_IN_FORBIDDEN_ZONE.value, 409)


class TestUnlockRiderState:
    def test_rider_with_no_other_active_ride_can_unlock(self, api):
        """PRD §3.4: 'The rider must be ACTIVE and must have no other
        ACTIVE Ride — otherwise ERR_RIDER_HAS_ACTIVE_RIDE.'"""
        # Positive baseline: a fresh rider unlocks successfully.
        ctx = setup_basic_ride_scenario()
        ride = start_ride(ctx["rider"], ctx["bike"])
        assert ride["status"] == "ACTIVE"

    def test_rider_with_existing_active_ride_rejected(self, api):
        """PRD §3.4: 'The rider must be ACTIVE and must have no other
        ACTIVE Ride — otherwise ERR_RIDER_HAS_ACTIVE_RIDE.'"""
        # Region with two bikes
        region, bikes = setup_region_with_bikes(num_bikes=2)
        rider = create_funded_rider()
        # Start one ride
        api.create_ride(
            create_ride_payload(rider_id=rider["id"], bike_id=bikes[0]["id"]),
            make_rider_headers(rider["id"]),
        )
        # Attempt a concurrent ride on the second bike
        resp = api.create_ride(
            create_ride_payload(rider_id=rider["id"], bike_id=bikes[1]["id"]),
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RIDER_HAS_ACTIVE_RIDE.value, 409)


class TestUnlockBalance:
    def test_wallet_at_minimum_unlock_balance_allows_unlock(self, api):
        """PRD §3.4: 'wallet_balance_cents is at least 100 cents —
        MIN_UNLOCK_BALANCE_CENTS, the minimum unlock balance.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        rider = create_funded_rider(wallet_balance_cents=100)
        ride = start_ride(rider, bikes[0])
        assert ride["status"] == "ACTIVE"

    def test_wallet_below_minimum_unlock_balance_rejected(self, api):
        """PRD §3.4: 'otherwise ERR_INSUFFICIENT_BALANCE (HTTP 402).'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        rider = create_funded_rider(wallet_balance_cents=99)
        resp = api.create_ride(
            create_ride_payload(rider_id=rider["id"], bike_id=bikes[0]["id"]),
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value, 402)

    def test_active_monthly_pass_bypasses_wallet_minimum(self, api):
        """PRD §3.4: 'either monthly_pass_expires_minute is strictly
        greater than the current clock_minutes (the pass is active),
        or wallet_balance_cents is at least 100 cents.'"""
        # Setup: rider has wallet=0 but an active monthly pass
        region, bikes = setup_region_with_bikes(num_bikes=1)
        # Pre-fund just enough for pass purchase, do not retain wallet
        rider = setup_rider_with_monthly_pass(wallet_balance_cents=0)
        # Even though wallet is 0, the active pass allows unlock.
        assert rider["monthly_pass_expires_minute"] > 0
        ride = start_ride(rider, bikes[0])
        assert ride["status"] == "ACTIVE"


class TestRiderOwnership:
    def test_rider_cannot_unlock_using_anothers_rider_id(self, api):
        """PRD §2.1: 'A rider may read and act only on their own Ride
        records and only on their own Rider record.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        owner = create_funded_rider()
        other = create_funded_rider()
        # `other` attempts to start a ride on behalf of `owner`'s rider_id.
        resp = api.create_ride(
            create_ride_payload(rider_id=owner["id"], bike_id=bikes[0]["id"]),
            make_rider_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
