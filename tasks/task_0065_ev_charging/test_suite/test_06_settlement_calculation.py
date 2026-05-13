"""Session settlement calculation: per-window rounding for electricity,
stacked discount factor for service fee, tax on (electricity + service),
and the final total.

PRD §3.4 (settlement workflow) and PRD §3.6 (settlement calculation).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_session_settlement_consistent,
    create_promo_activity,
    get_estimate,
    setup_charging_session,
    setup_ready_to_charge,
    setup_settled_session,
    setup_settled_session_for_recipe,
    append_curve_point,
    stop_session,
    iso_day,
    iso_z,
    validate_error,
)
from datetime import datetime, timezone


# ===========================================================================
# Per-window rounding (Step B)
# ===========================================================================
class TestElectricityFeePerWindowRounding:
    """PRD §3.4 / §3.6 Step B: 'For each of the three windows
    independently, multiply the window's milli-kWh by its rate from pv
    ..., divide by one thousand, and round half up to an integer cents
    value. Sum the three per-window cents totals to obtain
    electricity_fee_cents. The rounding order is pinned at the
    per-window level — rounding once on the summed milli-kWh is not
    equivalent and is not permitted.'"""

    def test_single_flat_window_settles_with_expected_electricity_fee(
        self, api,
    ):
        """Setup PRD §3.6 Step B base case: 15000 milli-kWh at flat 50
        cents/kWh = 750 cents (no rounding required)."""
        ctx = setup_settled_session_for_recipe(
            member_tier="SILVER", member_wallet_cents=100000,
        )
        session = ctx["session"]
        assert session["electricity_fee_cents"] == 750, (
            f"15000 milli * 50/1000 = 750 cents per Step B, "
            f"got {session['electricity_fee_cents']}"
        )

    def test_mixed_window_rounding_per_window_then_sum(self, api):
        """PRD §3.6 Step B: 'rounding once on the summed milli-kWh is
        not equivalent and is not permitted.'

        Recipe per SCAFFOLD_DIFFICULTY_DESIGN per_window_rounding
        instance: peak=37, flat=50, valley=23; BASIC tier;
        peak_milli=5005, flat_milli=3000, valley_milli=2005.

        Per-window components:
          - peak    = round_half_up(5005*37/1000)  = round_half_up(185.185) = 185
          - flat    = round_half_up(3000*50/1000)  = 150
          - valley  = round_half_up(2005*23/1000)  = round_half_up(46.115)  = 46

        Per-window sum = 381.
        """
        # Use a pricing version with the recipe rates.
        # Build a single-pile context with BASIC tier and the desired
        # rates.
        ctx = setup_ready_to_charge(
            member_tier="BASIC",
            member_wallet_cents=100000,
            pricing_overrides=dict(
                peak_rate_per_kwh_cents=37,
                flat_rate_per_kwh_cents=50,
                valley_rate_per_kwh_cents=23,
                service_fee_per_kwh_cents=0,
                tax_bps=0,
                peak_windows=[],
                valley_windows=[],
                tier_service_fee_discount_bps={
                    "BASIC": 0, "SILVER": 0, "GOLD": 0, "PLATINUM": 0,
                },
            ),
        )
        from test_helpers import create_session, start_session
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        session = start_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        # Build a curve such that deltas tagged by their respective
        # window_tag accumulate exactly to peak=5005, flat=3000,
        # valley=2005.  PRD §3.4 Step A: 'the cumulative-energy delta
        # between this sample and the previous one (or between zero
        # and the first sample) is attributed to the window_tag of the
        # destination sample.'
        # We seed cumulative_energy_milli as 5005 (PEAK) -> 8005 (FLAT)
        # -> 10010 (VALLEY). Deltas: 5005, 3000, 2005.
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:01:00.000Z",
            cumulative_energy_milli=5005,
            instant_power_kw=60.0,
            window_tag="PEAK",
        )
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:02:00.000Z",
            cumulative_energy_milli=8005,
            instant_power_kw=60.0,
            window_tag="FLAT",
        )
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:03:00.000Z",
            cumulative_energy_milli=10010,
            instant_power_kw=60.0,
            window_tag="VALLEY",
        )
        settled = stop_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        assert settled["status"] == "SETTLED"
        # Per-window-then-sum semantics:
        # peak    = round_half_up(5005*37/1000) = 185
        # flat    = round_half_up(3000*50/1000) = 150
        # valley  = round_half_up(2005*23/1000) = 46
        # total   = 381
        assert settled["electricity_fee_cents"] == 381, (
            f"per-window then sum must be 185+150+46=381, "
            f"got {settled['electricity_fee_cents']}"
        )


# ===========================================================================
# Service fee discount stacking (Step C)
# ===========================================================================
class TestServiceFeeStackedDiscount:
    """PRD §3.4 / §3.6 Step C: 'The two discounts stack multiplicatively
    rather than additively: form an effective factor equal to ten
    thousand minus the tier discount, multiplied by ten thousand minus
    the promo discount.'

    With tier_discount=500 bps (SILVER) and promo_discount=0 bps:
      effective_factor = 9500 * 10000 = 95_000_000
      base service for 15000 milli @ 20 cents/kWh = round_half_up(300) = 300
      service_fee_cents = round_half_up(300 * 95_000_000 / 100_000_000)
                        = round_half_up(285.0) = 285.
    """

    def test_silver_tier_no_promo_yields_expected_service_fee(self, api):
        ctx = setup_settled_session_for_recipe(
            member_tier="SILVER", member_wallet_cents=100000,
        )
        session = ctx["session"]
        assert session["service_fee_cents"] == 285, (
            f"SILVER tier 500 bps off 300 cents base = 285, "
            f"got {session['service_fee_cents']}"
        )

    def test_basic_tier_no_promo_yields_unchanged_service_fee(self, api):
        """Tier_discount=0, promo_discount=0 → effective_factor =
        10000*10000; service_fee_cents == base_service_cents."""
        # 15 kWh at 20 cents/kWh = 300 cents base service, no tax, no promo.
        ctx = setup_ready_to_charge(
            member_tier="BASIC",
            member_wallet_cents=100000,
            pricing_overrides=dict(
                peak_rate_per_kwh_cents=80,
                flat_rate_per_kwh_cents=50,
                valley_rate_per_kwh_cents=30,
                service_fee_per_kwh_cents=20,
                tax_bps=0,
                peak_windows=[],
                valley_windows=[],
                tier_service_fee_discount_bps={
                    "BASIC": 0, "SILVER": 0, "GOLD": 0, "PLATINUM": 0,
                },
            ),
        )
        from test_helpers import create_session, start_session
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        session = start_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:01:00.000Z",
            cumulative_energy_milli=15000,
            instant_power_kw=60.0,
            window_tag="FLAT",
        )
        settled = stop_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        assert settled["service_fee_cents"] == 300


# ===========================================================================
# Tax (Step D) and total
# ===========================================================================
class TestTaxAndTotal:
    """PRD §3.4 / §3.6 Step D: 'Add electricity_fee_cents and
    service_fee_cents, multiply by pv.tax_bps, divide by ten thousand,
    and round half up; the result is tax_cents. The session's
    total_cents is the sum of electricity_fee_cents, service_fee_cents,
    and tax_cents.'"""

    def test_total_equals_electricity_plus_service_plus_tax(self, api):
        ctx = setup_settled_session_for_recipe(
            member_tier="SILVER", member_wallet_cents=100000,
        )
        session = ctx["session"]
        assert_session_settlement_consistent(session)

    def test_silver_recipe_yields_expected_total_cents(self, api):
        """electricity=750 + service=285 + tax=round_half_up(1035*1300/10000)
        = round_half_up(134.55) = 135 → total=1170."""
        ctx = setup_settled_session_for_recipe(
            member_tier="SILVER", member_wallet_cents=100000,
        )
        session = ctx["session"]
        assert session["tax_cents"] == 135
        assert session["total_cents"] == 1170


# ===========================================================================
# Provisional estimate vs final
# ===========================================================================
class TestProvisionalEstimate:
    """PRD §3.4: 'A provisional settlement estimate is available while
    the session is CHARGING: it runs the same arithmetic ... against the
    curve points captured up to now, returning a snapshot of
    electricity_fee_cents, service_fee_cents, tax_cents, and total_cents
    without mutating any field.'"""

    def test_estimate_with_partial_curve_differs_from_final_after_more_curve(
        self, api,
    ):
        """Recipe per SCAFFOLD_DIFFICULTY_DESIGN
        session_total_provisional_vs_final: append one 10000 milli
        sample, capture estimate, then append a 15000 milli sample and
        stop. Final total must differ from estimate.

        With Pricing PV (peak=80, flat=50, valley=30, service_fee=20,
        tax_bps=1300, SILVER discount 500 bps):

        Estimate over 10 kWh (FLAT):
          electricity = 10000*50/1000 = 500
          base_service = 10000*20/1000 = 200; service = round_half_up(
            200 * 9500*10000/100_000_000) = round_half_up(190) = 190
          tax = round_half_up((500+190)*1300/10000) = round_half_up(89.7) = 90
          total = 780

        Final over 15 kWh (FLAT, deltas 10 + 5):
          electricity per-window: round_half_up(10000*50/1000)=500
                                + round_half_up(5000*50/1000)=250 → 750
          base_service = 15000*20/1000 = 300; service = 285
          tax = round_half_up(1035*1300/10000) = 135
          total = 1170
        """
        # Build the recipe context but don't add the 2nd curve point yet.
        ctx = setup_ready_to_charge(
            member_tier="SILVER",
            member_wallet_cents=100000,
            pricing_overrides=dict(
                peak_rate_per_kwh_cents=80,
                flat_rate_per_kwh_cents=50,
                valley_rate_per_kwh_cents=30,
                service_fee_per_kwh_cents=20,
                tax_bps=1300,
                peak_windows=[],
                valley_windows=[],
                tier_service_fee_discount_bps={
                    "BASIC": 0, "SILVER": 500, "GOLD": 1000, "PLATINUM": 1500,
                },
            ),
        )
        from test_helpers import create_session, start_session
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        session = start_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:01:00.000Z",
            cumulative_energy_milli=10000,
            instant_power_kw=60.0,
            window_tag="FLAT",
        )
        estimate = get_estimate(session["id"])
        assert estimate["electricity_fee_cents"] == 500
        assert estimate["total_cents"] == 780

        # Now append a second sample and stop.
        append_curve_point(
            session_id=session["id"],
            sampled_at="2026-05-13T00:02:00.000Z",
            cumulative_energy_milli=15000,
            instant_power_kw=60.0,
            window_tag="FLAT",
        )
        settled = stop_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        # Final total must differ from the captured estimate.
        assert settled["electricity_fee_cents"] == 750
        assert settled["total_cents"] == 1170
        assert settled["total_cents"] != estimate["total_cents"]
