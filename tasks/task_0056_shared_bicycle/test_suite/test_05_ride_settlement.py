"""End-of-ride settlement: per-minute, segment, daily cap, penalty, reward.

PRD §3.4 specifies the settlement formula with pinned evaluation order:
free coverage → pass coverage → segment math → daily cap → penalty
(reward credited to wallet separately).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_ride_settled_invariants,
    create_funded_rider,
    create_ride_payload,
    end_ride,
    end_ride_payload,
    get_rider,
    make_rider_headers,
    run_full_ride,
    setup_basic_ride_scenario,
    setup_region_with_allowed_parking,
    setup_region_with_restricted_zone,
    settle_simple_standard_ride,
    start_ride,
    validate_error,
    validate_success,
    ADMIN,
    OPERATOR,
)


class TestPerMinuteSegmentMath:
    """PRD §3.4: 'A STANDARD bike charges 30 cents per minute for the
    first 30 chargeable minutes ... and 50 cents per minute beyond.'"""

    def test_standard_under_segment_break_per_minute(self, api):
        """PRD §3.4: 'the first-segment portion is the smaller of
        chargeable_minutes and 30; the over-segment portion is whatever
        is left after the first 30, or zero if chargeable_minutes is
        at most 30.'"""
        ctx = settle_simple_standard_ride(duration_minutes=20)
        ride = ctx["ride"]
        assert_ride_settled_invariants(ride)
        assert ride["chargeable_minutes"] == 20
        assert ride["base_fare_cents"] == 20 * 30, (
            f"PRD §3.4: 20 * 30 = 600, got {ride['base_fare_cents']}"
        )
        assert ride["settlement_variant"] == "PER_MINUTE"

    def test_standard_over_segment_break_uses_over_rate(self, api):
        """PRD §3.4: 'over_seg * over_rate ... 50 cents per minute
        beyond.' At 35 chargeable minutes: 30*30 + 5*50 = 1150."""
        ctx = settle_simple_standard_ride(duration_minutes=35)
        ride = ctx["ride"]
        expected = 30 * 30 + 5 * 50
        assert ride["base_fare_cents"] == expected, (
            f"PRD §3.4: 30*30 + 5*50 = {expected}, "
            f"got {ride['base_fare_cents']}"
        )
        assert ride["settlement_variant"] == "PER_MINUTE"


class TestDailyCap:
    """PRD §3.4: 'A daily cap is then applied. The cap for a STANDARD
    bike is 1500 cents; for an E_BIKE it is 3000 cents.'"""

    def test_standard_below_cap_per_minute_variant(self, api):
        """PRD §3.4: 'If base_fare_cents is greater than or equal to the
        applicable cap, it is clamped to the cap and the ride's
        settlement_variant is recorded as DAILY_CAP; otherwise
        base_fare_cents is left as computed and the variant is
        PER_MINUTE.'"""
        # 41 chargeable: 30*30 + 11*50 = 900 + 550 = 1450 < 1500
        ctx = settle_simple_standard_ride(duration_minutes=41)
        ride = ctx["ride"]
        assert ride["base_fare_cents"] == 1450
        assert ride["settlement_variant"] == "PER_MINUTE"

    def test_standard_at_cap_clamps_and_records_daily_cap(self, api):
        """PRD §3.4: 'If base_fare_cents is greater than or equal to the
        applicable cap, it is clamped to the cap and the ride's
        settlement_variant is recorded as DAILY_CAP.'"""
        # 42 chargeable on STANDARD: 30*30 + 12*50 = 900 + 600 = 1500 → cap
        ctx = settle_simple_standard_ride(duration_minutes=42)
        ride = ctx["ride"]
        assert ride["base_fare_cents"] == 1500
        assert ride["settlement_variant"] == "DAILY_CAP"

    def test_standard_above_cap_clamped_to_1500(self, api):
        """PRD §3.4: 'it is clamped to the cap.'"""
        ctx = settle_simple_standard_ride(duration_minutes=100)
        ride = ctx["ride"]
        assert ride["base_fare_cents"] == 1500
        assert ride["settlement_variant"] == "DAILY_CAP"


class TestPenaltyAndReward:
    """PRD §3.4: penalty/reward stacking at end-of-ride."""

    def test_restricted_zone_adds_penalty_on_top_of_base(self, api):
        """PRD §3.4: 'If end_fence_kind is RESTRICTED, penalty_cents is
        set to the region's out_of_zone_penalty_cents.' AND 'final_fare_cents
        is the (possibly capped) base_fare_cents plus penalty_cents.'"""
        ctx = setup_region_with_restricted_zone(
            center_lat=30.5, center_lng=120.5, side=0.05,
            out_of_zone_penalty_cents=200,
            num_bikes=1,
        )
        rider = create_funded_rider(wallet_balance_cents=10000)
        ride = start_ride(rider, ctx["bikes"][0])
        advance_clock(10)  # 10 chargeable min → 300 cents on STANDARD
        settled = end_ride(ride, end_lat=ctx["restricted_lat"],
                           end_lng=ctx["restricted_lng"],
                           rider_id=rider["id"])
        assert settled["penalty_cents"] == 200
        assert settled["base_fare_cents"] == 300
        assert settled["final_fare_cents"] == 500, (
            "PRD §3.4: final = base (300) + penalty (200) = 500"
        )

    def test_reward_credited_to_wallet_not_netted(self, api):
        """PRD §3.4: 'final_fare_cents is the (possibly capped)
        base_fare_cents plus penalty_cents — the reward is not netted
        in, it is credited separately to the wallet.'"""
        ctx = setup_region_with_allowed_parking(
            center_lat=30.5, center_lng=120.5, side=0.05,
            in_zone_return_reward_cents=200,
            num_bikes=1,
        )
        rider = create_funded_rider(wallet_balance_cents=10000)
        ride = start_ride(rider, ctx["bikes"][0])
        advance_clock(10)
        settled = end_ride(ride, end_lat=ctx["allowed_lat"],
                           end_lng=ctx["allowed_lng"],
                           rider_id=rider["id"])
        # final_fare = base (300) + penalty (0) = 300; reward (200) is
        # credited separately.
        assert settled["base_fare_cents"] == 300
        assert settled["penalty_cents"] == 0
        assert settled["final_fare_cents"] == 300, (
            "PRD §3.4: reward is NOT netted into final_fare_cents"
        )
        assert settled["reward_cents"] == 200
        # Wallet: 10000 - 300 (debit) + 200 (reward credit) = 9900
        rider_after = get_rider(rider["id"])
        assert rider_after["wallet_balance_cents"] == 9900, (
            "PRD §3.4: wallet credited reward, debited final_fare"
        )

    def test_none_fence_no_penalty_no_reward(self, api):
        """PRD §3.4: 'producing end_fence_kind of ALLOWED_PARKING,
        RESTRICTED, or NONE.' NONE means no penalty and no reward."""
        ctx = settle_simple_standard_ride(duration_minutes=10)
        assert ctx["ride"]["penalty_cents"] == 0
        assert ctx["ride"]["reward_cents"] == 0


class TestFreeMinutesAndPass:
    def test_free_minutes_consumed_first(self, api):
        """PRD §3.4: 'The rider's free_minutes_remaining is consumed
        first: applied_free_minutes is the smaller of
        free_minutes_remaining and duration.'"""
        ctx = run_full_ride(
            duration_minutes=10,
            wallet_balance_cents=10000,
            free_minutes=5,
            end_lat=10.0, end_lng=10.0,  # NONE fence
        )
        ride = ctx["ride"]
        assert ride["applied_free_minutes"] == 5, (
            f"PRD §3.4: min(5, 10) = 5, got {ride['applied_free_minutes']}"
        )
        # chargeable = 10 - 5 - 0 = 5
        assert ride["chargeable_minutes"] == 5
        assert ride["base_fare_cents"] == 5 * 30

    def test_free_minutes_remaining_decremented(self, api):
        """PRD §3.4: 'Rider.free_minutes_remaining -= applied_free_minutes.'"""
        ctx = run_full_ride(
            duration_minutes=4,
            wallet_balance_cents=10000,
            free_minutes=10,
            end_lat=10.0, end_lng=10.0,
        )
        # min(10, 4) = 4 applied → remaining = 6
        rider_after = get_rider(ctx["rider"]["id"])
        assert rider_after["free_minutes_remaining"] == 6, (
            f"Expected 6 remaining free minutes, "
            f"got {rider_after['free_minutes_remaining']}"
        )

    def test_minimum_one_minute_billed(self, api):
        """PRD §3.4: 'Let duration be the larger of end_minute -
        start_minute and 1 — the minimum billed duration is one whole
        minute.'"""
        # End the ride at start_minute (advance_clock=0) — duration
        # should still be 1 (and chargeable = 1 with no free/pass).
        ctx = setup_basic_ride_scenario(wallet_balance_cents=10000)
        ride = start_ride(ctx["rider"], ctx["bike"])
        # Do NOT advance clock — settle immediately.
        settled = end_ride(ride, end_lat=10.0, end_lng=10.0,
                           rider_id=ctx["rider"]["id"])
        assert settled["chargeable_minutes"] == 1, (
            "PRD §3.4: minimum billed duration is one whole minute"
        )
        assert settled["base_fare_cents"] == 30

    def test_pass_does_not_cover_e_bike(self, api):
        """PRD §3.4: 'the pass covers minutes only on STANDARD bikes —
        it never covers any minute on an E_BIKE.'"""
        from test_helpers import (
            buy_monthly_pass, credit_wallet, create_bike,
            create_rider, shelf_bike_on, create_region,
        )
        # Build E_BIKE region + bike
        region = create_region(deployment_quota=10,
                               low_density_threshold=0,
                               high_density_threshold=999)
        bike = create_bike(model="E_BIKE", battery_pct=100)
        shelf_bike_on(region["id"], bike["id"])
        from test_helpers import get_bike
        bike = get_bike(bike["id"])
        rider = create_rider()
        credit_wallet(rider["id"], 100_000)  # cover pass + ride
        rider = buy_monthly_pass(rider["id"])
        # Start E_BIKE ride; even with active pass it should not cover
        ride = start_ride(rider, bike)
        advance_clock(10)
        settled = end_ride(ride, end_lat=10.0, end_lng=10.0,
                           rider_id=rider["id"])
        assert settled["pass_covered_minutes"] == 0, (
            "PRD §3.4: pass does not cover E_BIKE"
        )
        assert settled["chargeable_minutes"] == 10
        assert settled["base_fare_cents"] == 10 * 60, (
            "E_BIKE first-segment rate is 60 cents/min"
        )


class TestEndRideErrors:
    def test_end_ride_when_not_active_rejected(self, api):
        """PRD §3.4: 'The ride must still be ACTIVE — otherwise
        ERR_RIDE_NOT_ACTIVE.'"""
        ctx = settle_simple_standard_ride(duration_minutes=10)
        ride = ctx["ride"]
        # Settle again
        resp = api.end_ride(
            ride["id"],
            end_ride_payload(end_lat=10.0, end_lng=10.0),
            make_rider_headers(ctx["rider"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RIDE_NOT_ACTIVE.value, 409)

    def test_end_in_forbidden_zone_rejected(self, api):
        """PRD §3.4: 'the end coordinates must not fall inside any
        FORBIDDEN active Geofence in the bike's region_id — otherwise
        ERR_END_IN_FORBIDDEN_ZONE.'"""
        from test_helpers import setup_region_with_forbidden_zone, patch_bike
        ctx = setup_region_with_forbidden_zone(
            center_lat=30.5, center_lng=120.5, side=0.01, num_bikes=1,
        )
        # Move bike outside the forbidden zone so unlock succeeds.
        patch_bike(ctx["bikes"][0]["id"],
                   last_lat=ctx["outside_lat"],
                   last_lng=ctx["outside_lng"])
        rider = create_funded_rider()
        ride = start_ride(rider, ctx["bikes"][0])
        advance_clock(5)
        # End inside the forbidden zone
        resp = api.end_ride(
            ride["id"],
            end_ride_payload(end_lat=ctx["forbidden_lat"],
                             end_lng=ctx["forbidden_lng"]),
            make_rider_headers(rider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_END_IN_FORBIDDEN_ZONE.value, 409)
