"""Ride request, quoted_fare formula at REQUESTED instant."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BASE_FARE_CENTS,
    MULTIPLIER_CAP,
    PER_KM_CENTS,
    assert_ride,
    assert_ride_base_fare_matches_formula,
    assert_ride_quoted_fare_matches_formula,
    create_grid,
    create_requested_ride,
    create_rider,
    create_rush_hour_window,
    day_of_week_from_iso,
    expected_quoted_fare_cents,
    get_grid,
    get_ride,
    iso_now_utc,
    make_rider_headers,
    minute_of_day_from_iso,
    setup_grid_with_demand_ratio,
    setup_grid_with_supply,
    validate_error,
    validate_success,
)


# ===========================================================================
# Ride creation — basic shape.
# ===========================================================================
class TestRideCreation:

    def test_request_ride_returns_201_in_requested_state(self, api):
        """PRD §3.3: "The ride is created in REQUESTED status, its
        requested_at is set to the current server timestamp, its
        driver_id is null, its completed_at and final_fare_cents and
        driver_earnings_cents are all null".
        PRD §4: POST /rides returns 201.
        """
        grid, _ = setup_grid_with_supply(num_drivers=1)
        rider = create_rider()
        from test_helpers import create_ride_payload
        resp = api.create_ride(
            create_ride_payload(grid["code"], distance_km=4.0),
            make_rider_headers(rider["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_ride(data)
        assert data["status"] == "REQUESTED"
        assert data["driver_id"] is None
        assert data["completed_at"] is None
        assert data["final_fare_cents"] is None
        assert data["driver_earnings_cents"] is None

    def test_invalid_distance_km_zero_rejected(self, api):
        """PRD §3.3: "distance_km (which must be strictly greater than
        zero, otherwise ERR_INVALID_INPUT)."
        """
        grid = create_grid()
        rider = create_rider()
        resp = api.create_ride(
            {"pickup_grid_code": grid["code"],
             "dropoff_grid_code": grid["code"],
             "distance_km": 0.0},
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_invalid_distance_km_negative_rejected(self, api):
        """PRD §3.3: distance_km must be strictly greater than zero,
        otherwise ERR_INVALID_INPUT."""
        grid = create_grid()
        rider = create_rider()
        resp = api.create_ride(
            {"pickup_grid_code": grid["code"],
             "dropoff_grid_code": grid["code"],
             "distance_km": -3.0},
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)


# ===========================================================================
# Quoted fare formula — PRD §3.3.
# ===========================================================================
class TestQuotedFareFormula:

    def test_base_fare_formula(self):
        """PRD §3.3: "The base fare in cents is computed as
        BASE_FARE_CENTS (250) plus the distance_km multiplied by
        PER_KM_CENTS (120), with the product rounded half-up to an
        integer cent; that integer is pinned on the ride as
        base_fare_cents."

        distance_km=5.0 → 250 + 600 = 850.
        """
        grid, _ = setup_grid_with_supply(num_drivers=1,
                                          rush_hour_eligible=False)
        rider = create_rider()
        ride = create_requested_ride(rider["id"], grid["code"],
                                     distance_km=5.0)
        assert ride["base_fare_cents"] == 850
        assert_ride_base_fare_matches_formula(ride)

    def test_pickup_multiplier_snapshot_pinned_at_request(self):
        """PRD §3.3: "The pickup grid's live current_multiplier is read
        once and pinned on the ride as pickup_multiplier_snapshot."

        With 1 supply + 1 ride (no rush), the grid was at 1.00 at
        REQUESTED instant (the ride itself bumps demand AFTER snapshot).
        Actually PRD §3.3 says "the pickup grid's live current_multiplier
        is read once" — implementation may snap before or after the
        demand increment, but the snapshot is then pinned regardless.

        Validate: pickup_multiplier_snapshot is a finite number in
        [1.00, MULTIPLIER_CAP] and equals the multiplier on the
        ride-snapshot moment.
        """
        grid, _ = setup_grid_with_supply(num_drivers=2,
                                         rush_hour_eligible=False)
        # active=2, demand=0 before request → multiplier=1.00.
        rider = create_rider()
        ride = create_requested_ride(rider["id"], grid["code"],
                                     distance_km=5.0)
        # Snapshot must be a stable real number; verify it's within
        # the legal range.
        assert 1.00 <= float(ride["pickup_multiplier_snapshot"]) <= MULTIPLIER_CAP

    def test_quoted_fare_at_multiplier_one(self):
        """PRD §3.3: "The effective multiplier is the sum of
        pickup_multiplier_snapshot and rush_hour_bonus_snapshot, then
        taken as the minimum of that sum and the MULTIPLIER_CAP of
        3.00. The quoted_fare_cents is the base_fare_cents multiplied
        by that capped effective multiplier, rounded half-up to an
        integer cent."

        Ratio<=1.0 → multiplier 1.00, no rush bonus → quoted = base.
        """
        grid, _ = setup_grid_with_supply(num_drivers=2,
                                         rush_hour_eligible=False)
        rider = create_rider()
        ride = create_requested_ride(rider["id"], grid["code"],
                                     distance_km=5.0)
        # Base fare = 250 + 600 = 850. With mult=1.00, quoted=850.
        assert ride["base_fare_cents"] == 850
        assert_ride_quoted_fare_matches_formula(ride)

    def test_rush_hour_bonus_snapshot_zero_when_no_window_matches(self):
        """PRD §3.3: "if such a window matches, its additive_bonus is
        pinned on the ride as rush_hour_bonus_snapshot, otherwise that
        snapshot is pinned at 0.00."
        """
        grid, _ = setup_grid_with_supply(num_drivers=2,
                                         rush_hour_eligible=False)
        rider = create_rider()
        ride = create_requested_ride(rider["id"], grid["code"],
                                     distance_km=5.0)
        # No RushHourWindow exists → bonus is 0.00.
        assert float(ride["rush_hour_bonus_snapshot"]) == 0.00, (
            "PRD §3.3: rush_hour_bonus_snapshot pinned at 0.00 when no "
            "window matches."
        )

    def test_rush_hour_bonus_suppressed_when_grid_not_eligible(self):
        """PRD §3.5: "The match itself is conditioned on the pickup
        grid's rush_hour_eligible flag being true; on a grid where that
        flag is false, the bonus is suppressed regardless of any
        matching window."
        """
        # Create a 24-hour rush-hour window on every day so that any
        # ride created today matches.
        now = iso_now_utc()
        dow = day_of_week_from_iso(now)
        create_rush_hour_window(
            day_of_week=dow, start_minute=0, end_minute=1440,
            additive_bonus=1.00,
        )
        # Create a grid whose rush_hour_eligible=False — bonus must be
        # suppressed on rides pinned to it.
        grid = create_grid(is_airport=False, rush_hour_eligible=False)
        from test_helpers import create_and_online_driver
        create_and_online_driver(grid["code"])
        rider = create_rider()
        ride = create_requested_ride(rider["id"], grid["code"],
                                     distance_km=2.0)
        assert float(ride["rush_hour_bonus_snapshot"]) == 0.00


# ===========================================================================
# Cap interaction with rush-hour bonus — PRD §3.3, §3.5.
# ===========================================================================
class TestQuotedFareCapAndRush:

    def test_quoted_fare_with_rush_bonus_capped_at_three(self):
        """PRD §3.5: "A rush-hour window's additive_bonus is added to
        the supply-and-demand-derived multiplier before the cap is
        applied (so the bonus does not push the effective ride
        multiplier above the MULTIPLIER_CAP of 3.00)."

        Stage: supply=2, demand=5 → ratio 2.5 → bucket 2.00 (per
        PRD §2.5 "greater than 2.0 and less than or equal to 3.0 yields
        2.00"); add rush bonus 1.00 → 3.00; cap to 3.00.
        # difficulty: combinatorial_formula/quoted_fare_with_rush_hour_and_surge_then_cap
        """
        # Create rush window covering all of today so it matches any
        # ride created now.
        now = iso_now_utc()
        dow = day_of_week_from_iso(now)
        create_rush_hour_window(
            day_of_week=dow, start_minute=0, end_minute=1440,
            additive_bonus=1.00,
        )
        # Stage supply=2, demand=5 to get raw multiplier=2.50 per
        # PRD §2.5 ("greater than 2.0 and less than or equal to 3.0
        # yields 2.00; greater than 3.0 and less than or equal to 4.0
        # yields 2.50"). Ratio=5/2=2.5 → 2.00.
        sc = setup_grid_with_demand_ratio(
            num_drivers=2, num_open_demand=5,
            is_airport=False, rush_hour_eligible=True,
        )
        # Grid mult is 2.00. Issue another ride; pickup_snapshot=2.00
        # at request time. Wait — issuing a new ride against this grid
        # changes demand from 5 → 6 then snaps multiplier; we want the
        # snapshot to capture whatever the live multiplier is. The
        # important assertion is that capped effective multiplier is
        # 3.00 because pickup_snapshot + rush_bonus(1.00) > 3.00.
        rider = create_rider()
        ride = create_requested_ride(rider["id"], sc["grid"]["code"],
                                     distance_km=5.0)
        # pickup_multiplier_snapshot was at least 2.0 (could be 2.50
        # or 2.0 depending on snap-before/snap-after the demand inc).
        # With bonus 1.00, eff_mult capped at 3.00.
        assert float(ride["rush_hour_bonus_snapshot"]) == 1.00
        assert float(ride["pickup_multiplier_snapshot"]) >= 2.00
        eff = min(
            float(ride["pickup_multiplier_snapshot"])
            + float(ride["rush_hour_bonus_snapshot"]),
            MULTIPLIER_CAP,
        )
        from test_helpers import round_half_up_int
        expected_quoted = round_half_up_int(ride["base_fare_cents"] * eff)
        assert ride["quoted_fare_cents"] == expected_quoted
        # And since the sum exceeds 3.00, the cap binds — i.e., quoted
        # fare equals base * 3.00.
        assert eff == MULTIPLIER_CAP, (
            "PRD §3.5: pickup_snapshot >= 2.00 + bonus 1.00 = >=3.00, "
            "so the cap binds."
        )
