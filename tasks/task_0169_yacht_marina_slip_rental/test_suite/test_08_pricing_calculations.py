"""Pricing calculations — PRD §3.5.

Two distinct totals on each reservation:
- estimated_total_cents (forward-looking) — set at APPROVE; freezes the
  season multiplier of check_in_date across all nights.
- final_total_cents (chronological) — set at CHECK_OUT; re-evaluates the
  season multiplier per night.

Per-night raw = base_daily_rate_cents * loa_feet * season_multiplier
              + flat_daily_charge_cents
              + (liveaboard ? 1500 : 0)
Per-night charge = round_half_up(per_night_raw)
Total = per_night_charge * nights (forward) or summed per night
(chronological).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to_iso,
    approve_reservation,
    check_in_reservation,
    check_out_reservation,
    get_reservation,
    setup_approved_reservation,
    setup_checked_out_reservation,
    setup_draft_reservation,
)


# ===========================================================================
# Forward-looking estimate — PRD §3.5
# ===========================================================================
class TestForwardLookingEstimate:

    def test_off_season_single_night_no_liveaboard(
        self, api, dock_master_headers,
    ):
        """PRD §3.5: "The per-night raw amount is built from three
        additive ingredients. The first is the marina's
        `base_daily_rate_cents` multiplied by the vessel's `loa_feet`
        and then multiplied by the season multiplier for that night.
        The second is the slip's `flat_daily_charge_cents`, a constant
        added on top regardless of vessel size or season. The third,
        applied only when the reservation's `liveaboard` flag is true,
        is the liveaboard surcharge of 1500 cents."

        With base=500, LOA=30, off-season multiplier=1.00, slip
        flat=2000, no liveaboard:
          per_night_raw = 500 * 30 * 1.00 + 2000 + 0 = 17000
          per_night = round_half_up(17000) = 17000
          estimated = 17000 * 1 night = 17000.
        """
        scenario = setup_approved_reservation(
            check_in_date="2024-02-01T00:00:00.000Z",
            check_out_date="2024-02-02T00:00:00.000Z",
            liveaboard=False,
            base_daily_rate_cents=500,
            slip_length_feet=40.0,
            slip_beam_feet=14.0,
            slip_depth_feet=6.0,
            slip_flat_daily_charge_cents=2000,
            slip_liveaboard_allowed=False,
            vessel_loa_feet=30.0,
            vessel_beam_feet=10.0,
            vessel_draft_feet=4.0,
        )
        assert scenario["reservation"]["estimated_total_cents"] == 17000, (
            f"Expected estimated_total_cents=17000, got "
            f"{scenario['reservation']['estimated_total_cents']!r}"
        )

    def test_peak_season_freezes_across_term_crossing_boundary(
        self, api, dock_master_headers,
    ):
        """PRD §3.5: "The forward-looking calculation runs at approval.
        It looks up the season multiplier for `check_in_date` and
        freezes it; every night in the term is priced using that same
        multiplier, regardless of whether the term crosses a season
        boundary."

        With base=500, LOA=30, slip flat=2000, no liveaboard, check_in
        2024-08-30 (PEAK, multiplier 1.50) and check_out 2024-09-02
        (3 nights, crossing into SHOULDER):
          per_night_raw = 500 * 30 * 1.50 + 2000 + 0 = 24500
          per_night = round_half_up(24500) = 24500
          estimated = 24500 * 3 = 73500.
        """
        scenario = setup_approved_reservation(
            check_in_date="2024-08-30T00:00:00.000Z",
            check_out_date="2024-09-02T00:00:00.000Z",
            liveaboard=False,
            base_daily_rate_cents=500,
            slip_length_feet=40.0,
            slip_beam_feet=14.0,
            slip_depth_feet=6.0,
            slip_flat_daily_charge_cents=2000,
            slip_liveaboard_allowed=False,
            vessel_loa_feet=30.0,
            vessel_beam_feet=10.0,
            vessel_draft_feet=4.0,
        )
        assert scenario["reservation"]["estimated_total_cents"] == 73500, (
            f"Expected estimated_total_cents=73500 (3 nights at PEAK "
            f"frozen), got "
            f"{scenario['reservation']['estimated_total_cents']!r}"
        )

    def test_liveaboard_surcharge_added_to_per_night(
        self, api, dock_master_headers,
    ):
        """PRD §3.5: "The third, applied only when the reservation's
        `liveaboard` flag is true, is the liveaboard surcharge of 1500
        cents."

        With base=500, LOA=30, peak multiplier 1.50, slip flat=2000,
        liveaboard=true, 5 nights 2024-07-10 → 2024-07-15:
          per_night_raw = 500 * 30 * 1.50 + 2000 + 1500 = 26000
          per_night = round_half_up(26000) = 26000
          estimated = 26000 * 5 = 130000.
        """
        scenario = setup_approved_reservation(
            check_in_date="2024-07-10T00:00:00.000Z",
            check_out_date="2024-07-15T00:00:00.000Z",
            liveaboard=True,
            base_daily_rate_cents=500,
            slip_length_feet=40.0,
            slip_beam_feet=14.0,
            slip_depth_feet=6.0,
            slip_flat_daily_charge_cents=2000,
            slip_liveaboard_allowed=True,
            vessel_loa_feet=30.0,
            vessel_beam_feet=10.0,
            vessel_draft_feet=4.0,
            vessel_holding_tank_gallons=40,
            liveaboard_quota=5,
        )
        assert scenario["reservation"]["estimated_total_cents"] == 130000, (
            f"Expected estimated_total_cents=130000 (5 nights at PEAK "
            f"with liveaboard surcharge), got "
            f"{scenario['reservation']['estimated_total_cents']!r}"
        )


# ===========================================================================
# Rounding order — PRD §2.8 / §3.5
# ===========================================================================
class TestRoundingOrder:

    def test_per_night_rounded_then_summed(
        self, api, dock_master_headers,
    ):
        """PRD §2.8: "When a per-night price requires rounding (because
        a season multiplier produces a fractional cent), the per-night
        raw amount is rounded half-up to a whole cent before any
        aggregation across nights. Multi-night totals are then exact
        integer sums of these rounded per-night amounts."

        With base=167, LOA=30.5, shoulder multiplier 1.20, slip
        flat=1000, no liveaboard, 3 nights in April (SHOULDER):
          per_night_raw = 167 * 30.5 * 1.20 + 1000 = 6112.2 + 1000 = 7112.2
          per_night = round_half_up(7112.2) = 7112
          estimated = 7112 * 3 = 21336.

        An implementation that sums-then-rounds (incorrect) would
        produce round_half_up(7112.2 * 3) = 21337. The PRD pins
        21336."""
        scenario = setup_approved_reservation(
            check_in_date="2024-04-10T00:00:00.000Z",
            check_out_date="2024-04-13T00:00:00.000Z",
            liveaboard=False,
            base_daily_rate_cents=167,
            slip_length_feet=40.0,
            slip_beam_feet=14.0,
            slip_depth_feet=6.0,
            slip_flat_daily_charge_cents=1000,
            slip_liveaboard_allowed=False,
            vessel_loa_feet=30.5,
            vessel_beam_feet=10.0,
            vessel_draft_feet=4.0,
        )
        assert scenario["reservation"]["estimated_total_cents"] == 21336, (
            f"Expected estimated_total_cents=21336 (per-night rounded "
            f"then summed), got "
            f"{scenario['reservation']['estimated_total_cents']!r} "
            f"— an implementation that sums then rounds yields 21337."
        )


# ===========================================================================
# Chronological final — PRD §3.5
# ===========================================================================
class TestChronologicalFinal:

    def test_final_re_evaluates_season_per_night_crossing_boundary(
        self, api, dock_master_headers,
    ):
        """PRD §3.5: "The chronological calculation runs at check-out.
        It walks every night date in `[check_in_date, check_out_date)`
        in ascending chronological order, looks up that night's season
        multiplier, computes the raw per-night amount for that night...
        A term that crosses a season boundary therefore produces a
        different number than the forward-looking estimate..."

        With base=500, LOA=30, slip flat=2000, no liveaboard:
          night 2024-08-30 (PEAK, 1.50): 500*30*1.50+2000 = 24500
          night 2024-08-31 (PEAK, 1.50): 24500
          night 2024-09-01 (SHOULDER, 1.20): 500*30*1.20+2000 = 20000
          final_total_cents = 24500 + 24500 + 20000 = 69000.

        Forward estimate was 73500 (3 nights at frozen PEAK)."""
        scenario = setup_checked_out_reservation(
            check_in_date="2024-08-30T00:00:00.000Z",
            check_out_date="2024-09-02T00:00:00.000Z",
            liveaboard=False,
            base_daily_rate_cents=500,
            slip_length_feet=40.0,
            slip_beam_feet=14.0,
            slip_depth_feet=6.0,
            slip_flat_daily_charge_cents=2000,
            slip_liveaboard_allowed=False,
            vessel_loa_feet=30.0,
            vessel_beam_feet=10.0,
            vessel_draft_feet=4.0,
        )
        reservation = scenario["reservation"]
        assert reservation["final_total_cents"] == 69000, (
            f"Expected final_total_cents=69000 (peak+peak+shoulder), "
            f"got {reservation['final_total_cents']!r}"
        )
        # And the forward-looking estimate frozen at PEAK should be
        # 73500.
        assert reservation["estimated_total_cents"] == 73500, (
            f"Expected estimated_total_cents=73500 (3 nights at frozen "
            f"PEAK), got {reservation['estimated_total_cents']!r}"
        )
        # The two MUST differ for a term that crosses a season boundary.
        assert (
            reservation["estimated_total_cents"]
            != reservation["final_total_cents"]
        ), (
            "Forward vs chronological must differ across a season "
            "boundary; this is the PRD-pinned divergence."
        )

    def test_final_same_as_estimate_within_one_season(
        self, api, dock_master_headers,
    ):
        """PRD §3.5: "Both calculations are integer-cent arithmetic
        throughout; rounding happens once per night at the per-night
        step, never on the running total."

        Within a single season, forward and chronological MUST agree
        (same per-night multiplier on every night).
        """
        scenario = setup_checked_out_reservation(
            check_in_date="2024-04-10T00:00:00.000Z",
            check_out_date="2024-04-13T00:00:00.000Z",
            liveaboard=False,
            base_daily_rate_cents=167,
            slip_length_feet=40.0,
            slip_beam_feet=14.0,
            slip_depth_feet=6.0,
            slip_flat_daily_charge_cents=1000,
            slip_liveaboard_allowed=False,
            vessel_loa_feet=30.5,
            vessel_beam_feet=10.0,
            vessel_draft_feet=4.0,
        )
        reservation = scenario["reservation"]
        assert reservation["final_total_cents"] == 21336, (
            f"Expected final_total_cents=21336 within shoulder season, "
            f"got {reservation['final_total_cents']!r}"
        )
        assert (
            reservation["estimated_total_cents"]
            == reservation["final_total_cents"]
        ), (
            "Forward and chronological MUST agree when the term lies "
            "entirely within one season."
        )
