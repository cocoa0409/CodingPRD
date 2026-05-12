"""Fee calculation — affiliation rates, peak multiplier, modes,
estimated vs final divergence.

PRD §3.5 (Billing rules and fee calculation), §2.6 (round-half-up),
§2.7 (peak windows).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock_to,
    check_in,
    check_out,
    create_lab_with_owner,
    create_verified_user,
    draft_and_publish_billing_rule,
    make_reservation,
    register_equipment,
    request_and_approve_authorization,
    set_clock_initial,
    setup_basic_scenario,
)


# ===========================================================================
# Affiliation tier selection (PRD §3.5)
# ===========================================================================
class TestAffiliationTier:
    """PRD §3.5: 'It picks the time and sample rates according to the
    user's affiliation: WITHIN_SCHOOL users get internal_rate_per_hour
    _cents and internal_rate_per_sample_cents; INTER_SCHOOL users get
    inter_school_rate_per_hour_cents and inter_school_rate_per_sample
    _cents; EXTERNAL users get external_rate_per_hour_cents and
    external_rate_per_sample_cents.'
    """

    def test_within_school_uses_internal_rate(self, api):
        """PRD §3.5: 'WITHIN_SCHOOL users get internal_rate_per_hour_cents'.

        Setup: BY_TIME mode, internal rate 10000 cents/hour, 2h
        reservation off-peak. Expected:
          equipment_fee = 2 * 10000 = 20000
          platform_fee = round(20000 * 0.10) = 2000
          consumables = 500
          estimated_fee = 22500
        """
        s = setup_basic_scenario(
            user_affiliation="WITHIN_SCHOOL",
            mode="BY_TIME",
            internal_rate_per_hour_cents=10000,
            peak_multiplier_bps=12500,
            platform_fee_bps=1000,
            consumables_flat_cents=500,
            initial_clock="2026-05-12T08:00:00.000Z",
        )
        r = make_reservation(
            equipment=s["equipment"], user=s["user"],
            authorization=s["authorization"],
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
            requested_sample_count=0,
        )
        assert r["estimated_fee_cents"] == 22500

    def test_external_uses_external_rate(self, api):
        """PRD §3.5: 'EXTERNAL users get external_rate_per_hour_cents'.

        Setup: BY_TIME, external rate 20000, sharing_scope=EXTERNAL so
        the user passes the eligibility gate. 2h reservation off-peak.
        Expected:
          equipment_fee = 2 * 20000 = 40000
          platform_fee = round(40000 * 0.10) = 4000
          consumables = 500
          estimated_fee = 44500
        """
        s = setup_basic_scenario(
            user_affiliation="EXTERNAL",
            sharing_scope="EXTERNAL",
            mode="BY_TIME",
            internal_rate_per_hour_cents=10000,
            peak_multiplier_bps=12500,
            platform_fee_bps=1000,
            consumables_flat_cents=500,
            initial_clock="2026-05-12T08:00:00.000Z",
        )
        r = make_reservation(
            equipment=s["equipment"], user=s["user"],
            authorization=s["authorization"],
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
        )
        assert r["estimated_fee_cents"] == 44500


# ===========================================================================
# Owner share derivation (PRD §3.5)
# ===========================================================================
class TestOwnerShareDerivation:
    """PRD §3.5: 'estimated_owner_share_cents equals the equipment-fee
    subtotal multiplied by the lab's revenue_share_bps, divided by 10000,
    rounded half-up to a whole number of cents.'
    """

    def test_owner_share_off_peak(self, api):
        """PRD §3.5: '... multiplied by the lab's revenue_share_bps,
        divided by 10000, rounded half-up'.

        equipment_fee=20000, revenue_share_bps=8000 →
        round(20000 * 0.8) = 16000.
        """
        s = setup_basic_scenario(
            user_affiliation="WITHIN_SCHOOL",
            revenue_share_bps=8000,
            mode="BY_TIME",
            internal_rate_per_hour_cents=10000,
            peak_multiplier_bps=12500,
            platform_fee_bps=1000,
            consumables_flat_cents=500,
            initial_clock="2026-05-12T08:00:00.000Z",
        )
        r = make_reservation(
            equipment=s["equipment"], user=s["user"],
            authorization=s["authorization"],
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
        )
        assert r["estimated_owner_share_cents"] == 16000


# ===========================================================================
# Estimated vs final divergence (PRD §3.5)
# ===========================================================================
class TestEstimatedVsFinal:
    """PRD §3.5: 'Because the estimated and final calculations use
    different billed-hours conventions (rational duration versus
    ceil-to-whole-hour) and different sample counts (requested_sample
    _count versus actual_sample_count), the two figures will diverge
    whenever the actual session overruns or under-runs the booking
    window, or the user reports a different sample count at checkout.'
    """

    def test_overrun_drives_final_above_estimated(self, api):
        """PRD §3.5: 'The actual billed hours figure is the ceiling, in
        whole hours, of the actual elapsed minutes divided by 60 (any
        partial hour rounds up).'

        Setup: 2h reservation, but check-out 1 minute past end →
        121 minutes → ceil(121/60) = 3 billed hours → final fee uses 3h.
        """
        s = setup_basic_scenario(
            user_affiliation="WITHIN_SCHOOL",
            revenue_share_bps=8000,
            mode="BY_TIME",
            internal_rate_per_hour_cents=10000,
            peak_multiplier_bps=12500,
            platform_fee_bps=1000,
            consumables_flat_cents=500,
            single_user_duration_limit_hours=8,
            peak_window_start_hour=22,
            peak_window_end_hour=23,
            initial_clock="2026-05-12T08:00:00.000Z",
        )
        r = make_reservation(
            equipment=s["equipment"], user=s["user"],
            authorization=s["authorization"],
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
        )
        assert r["estimated_fee_cents"] == 22500
        advance_clock_to("2026-05-12T09:00:00.000Z")
        r = check_in(reservation=r, user=s["user"])
        advance_clock_to("2026-05-12T11:01:00.000Z")
        completed = check_out(reservation=r, user=s["user"])
        # equipment_fee = 3 * 10000 = 30000; platform = 3000; consum=500
        # final_fee = 33500
        assert completed["final_fee_cents"] == 33500
        assert completed["final_fee_cents"] != completed["estimated_fee_cents"]


# ===========================================================================
# Peak multiplier (PRD §3.5)
# ===========================================================================
class TestPeakMultiplier:
    """PRD §3.5: 'When the reservation's window overlaps the equipment's
    daily peak window for strictly more than zero minutes ..., the raw
    time component is multiplied by peak_multiplier_bps divided by
    10000 — this multiplier is applied to the time portion only, never
    to the sample portion, and applied to the raw rational value before
    any rounding.'
    """

    def test_peak_overlap_triggers_multiplier(self, api):
        """PRD §3.5: 'multiplied by peak_multiplier_bps divided by 10000
        ... applied to the time portion only'.

        Setup: peak window 22-23 UTC, 1h reservation [22:00, 23:00) →
        60 min peak overlap. internal_rate=10000, peak_multiplier=12500
        → time_raw = 10000 * 1.25 = 12500. platform = round(12500*0.10)
        = 1250. consum = 500. estimated_fee = 14250.
        """
        s = setup_basic_scenario(
            user_affiliation="WITHIN_SCHOOL",
            mode="BY_TIME",
            internal_rate_per_hour_cents=10000,
            peak_multiplier_bps=12500,
            platform_fee_bps=1000,
            consumables_flat_cents=500,
            peak_window_start_hour=22,
            peak_window_end_hour=23,
            initial_clock="2026-05-12T20:00:00.000Z",
        )
        r = make_reservation(
            equipment=s["equipment"], user=s["user"],
            authorization=s["authorization"],
            start_at="2026-05-12T22:00:00.000Z",
            end_at="2026-05-12T23:00:00.000Z",
        )
        assert r["priority_tier"] == "PEAK"
        assert r["estimated_fee_cents"] == 14250


# ===========================================================================
# BY_SAMPLE mode (PRD §3.5)
# ===========================================================================
class TestBySampleMode:
    """PRD §3.5: 'The raw time component depends on mode. When the mode
    is BY_TIME it equals the billed hours multiplied by the
    affiliation-tier time rate. When the mode is BY_SAMPLE it is 0 ...
    The raw sample component is 0 when the mode is BY_TIME, and equals
    requested_sample_count multiplied by the affiliation-tier sample rate
    when the mode is BY_SAMPLE or HYBRID.'
    """

    def test_by_sample_excludes_time_component(self, api):
        """PRD §3.5: 'When the mode is BY_SAMPLE it is 0 ... the raw
        sample component ... equals requested_sample_count multiplied by
        the affiliation-tier sample rate'.

        Setup: BY_SAMPLE, internal_sample_rate=500, 4 samples →
        sample_raw = 4*500 = 2000. time_raw = 0.
        equipment_fee = 2000. platform = round(2000*0.10)=200.
        consum = 500. estimated_fee = 2700.
        """
        s = setup_basic_scenario(
            user_affiliation="WITHIN_SCHOOL",
            mode="BY_SAMPLE",
            internal_rate_per_hour_cents=10000,
            internal_rate_per_sample_cents=500,
            peak_multiplier_bps=12500,
            platform_fee_bps=1000,
            consumables_flat_cents=500,
            peak_window_start_hour=22,
            peak_window_end_hour=23,
            initial_clock="2026-05-12T08:00:00.000Z",
        )
        r = make_reservation(
            equipment=s["equipment"], user=s["user"],
            authorization=s["authorization"],
            start_at="2026-05-12T09:00:00.000Z",
            end_at="2026-05-12T11:00:00.000Z",
            requested_sample_count=4,
        )
        assert r["estimated_fee_cents"] == 2700
