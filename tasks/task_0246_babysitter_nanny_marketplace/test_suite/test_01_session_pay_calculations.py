"""Estimated vs. final session pay, overtime/multi-child/holiday/last-minute
combinatorial pay, and the OT and last-minute boundary behaviour.

Translates difficulty instances under dual_variant_calc, combinatorial_formula,
and the OT-boundary half of boundary_precision_check, plus the corner
calculations instance for the last-minute surcharge.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    setup_confirmed_one_time_booking, complete_session,
    make_caregiver_headers, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


class TestEstimatedVsFinalPayDiverge:
    """dual_variant_calc / estimated_vs_final_session_pay_diverge_on_overtime."""

    def test_estimated_pay_from_scheduled_window(self, api):
        """PRD §3.6: "First, the scheduled hours are the span from `scheduled_start`
        to `scheduled_end` expressed in hours, rounded to two decimal places."
        PRD §3.6: "The resulting `estimated_pay_cents` is the gross rounded to
        whole cents, round-half-up. This estimate drives the escrow reservation."

        Estimate: 6.0 scheduled h * 2000 * (1 + 0.10*1 child) = 6.0*2200 = 13200.

        Design: Difficulty/dual_variant_calc/estimated_vs_final_session_pay_diverge_on_overtime
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=2, required_tier="BASIC",
            agreed_rate_cents=2000,
            scheduled_start="2026-03-15T08:00:00Z", scheduled_end="2026-03-15T14:00:00Z",
            is_holiday=False, email_suffix="dv1est")
        assert ctx["booking"]["estimated_pay_cents"] == 13200, \
            f"expected estimate 13200, got {ctx['booking']['estimated_pay_cents']}"

    def test_final_pay_from_actual_hours_crossing_ot(self, api):
        """PRD §3.6: "the actual hours are split at the 8.0-hour daily threshold,
        with regular hours at the effective rate and overtime hours at the
        effective rate times the 1.5 overtime multiplier."
        PRD §3.6: "Because actual hours can diverge from the schedule — a
        caregiver working longer, shorter, or crossing the overtime boundary —
        the final pay can legitimately differ from the estimate."

        Final from 8.5 actual h, rate 2000, 2 children:
        eff = 2200; 8*2200 + 0.5*2200*1.5 = 17600 + 1650 = 19250 != 13200.

        Design: Difficulty/dual_variant_calc/estimated_vs_final_session_pay_diverge_on_overtime
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=2, required_tier="BASIC",
            agreed_rate_cents=2000,
            scheduled_start="2026-03-15T08:00:00Z", scheduled_end="2026-03-15T14:00:00Z",
            is_holiday=False, email_suffix="dv1fin")
        completed = complete_session(
            ctx["session"], ctx["caregiver"]["id"],
            clock_in="2026-03-15T08:00:00Z", clock_out="2026-03-15T16:30:00Z")
        assert completed["gross_pay_cents"] == 19250, \
            f"expected final 19250, got {completed['gross_pay_cents']}"
        assert completed["gross_pay_cents"] != ctx["booking"]["estimated_pay_cents"], \
            "final pay should diverge from the estimate when crossing the OT boundary"


class TestCombinatorialFinalPay:
    """combinatorial_formula / final_pay_three_inputs_nonlinear_overtime_multichild."""

    def test_final_pay_overtime_multichild_nonlinear(self, api):
        """PRD §3.6: "The `actual_hours` are the span from `clock_in_at` to
        `clock_out_at` in hours, rounded to two decimal places round-half-up."
        PRD §3.6: "the actual hours are split at the 8.0-hour daily threshold,
        with regular hours at the effective rate and overtime hours at the
        effective rate times the 1.5 overtime multiplier."

        8.5 actual h, rate 2000, num_children 2 → 19250, with the 8h knee.

        Design: Difficulty/combinatorial_formula/final_pay_three_inputs_nonlinear_overtime_multichild
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=2, required_tier="BASIC",
            agreed_rate_cents=2000,
            scheduled_start="2026-03-15T08:00:00Z", scheduled_end="2026-03-15T14:00:00Z",
            is_holiday=False, email_suffix="cf1")
        completed = complete_session(
            ctx["session"], ctx["caregiver"]["id"],
            clock_in="2026-03-15T08:00:00Z", clock_out="2026-03-15T16:30:00Z")
        assert completed["actual_hours"] == pytest.approx(8.5, abs=0.001), \
            f"expected actual_hours 8.5, got {completed['actual_hours']}"
        assert completed["gross_pay_cents"] == 19250, \
            f"expected gross 19250, got {completed['gross_pay_cents']}"

    def test_final_pay_overtime_multichild_distinct_estimate(self, api):
        """PRD §3.6: "A multi-child surcharge multiplier is formed as 1 plus a
        per-extra-child surcharge of 10 percent for each child beyond the first
        — that is, 1 plus 0.10 times the quantity (`num_children` minus 1)."

        Re-asserts the combinatorial gross via the actual-hours boundary on the
        clocked-out session, independent of the estimate.

        Design: Difficulty/combinatorial_formula/final_pay_three_inputs_nonlinear_overtime_multichild
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=2, required_tier="BASIC",
            agreed_rate_cents=2000,
            scheduled_start="2026-03-15T08:00:00Z", scheduled_end="2026-03-15T14:00:00Z",
            is_holiday=False, email_suffix="cf1b")
        completed = complete_session(
            ctx["session"], ctx["caregiver"]["id"],
            clock_in="2026-03-15T08:00:00Z", clock_out="2026-03-15T16:30:00Z")
        session = validate_success(api.get_session(completed["id"], ADMIN), 200)
        assert session["gross_pay_cents"] == 19250


class TestOvertimeBoundary:
    """boundary_precision_check / overtime_boundary_exactly_eight_hours_no_ot."""

    def test_exactly_eight_hours_no_overtime(self, api):
        """PRD §3.6: "the regular hours are the lesser of the scheduled hours and
        8.0, and the overtime hours are the scheduled hours beyond 8.0 (zero if
        the session is shorter)."

        8.00 actual h, rate 2000, 1 child: no OT → 8.00*2000 = 16000.

        Design: Difficulty/boundary_precision_check/overtime_boundary_exactly_eight_hours_no_ot
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=1, required_tier="BASIC",
            agreed_rate_cents=2000,
            scheduled_start="2026-03-18T08:00:00Z", scheduled_end="2026-03-18T16:00:00Z",
            is_holiday=False, email_suffix="otb")
        completed = complete_session(
            ctx["session"], ctx["caregiver"]["id"],
            clock_in="2026-03-18T08:00:00Z", clock_out="2026-03-18T16:00:00Z")
        assert completed["actual_hours"] == pytest.approx(8.0, abs=0.001), \
            f"expected actual_hours 8.0, got {completed['actual_hours']}"
        assert completed["gross_pay_cents"] == 16000, \
            f"expected gross 16000 (no OT at exactly 8h), got {completed['gross_pay_cents']}"

    def test_exactly_eight_hours_no_overtime_via_get(self, api):
        """PRD §3.6: "when it is not a holiday, hours are split at the daily
        overtime threshold of 8.0 hours".

        Confirms the persisted session reflects 16000 (no OT stacking at 8.0h).

        Design: Difficulty/boundary_precision_check/overtime_boundary_exactly_eight_hours_no_ot
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=1, required_tier="BASIC",
            agreed_rate_cents=2000,
            scheduled_start="2026-03-18T08:00:00Z", scheduled_end="2026-03-18T16:00:00Z",
            is_holiday=False, email_suffix="otb2")
        completed = complete_session(
            ctx["session"], ctx["caregiver"]["id"],
            clock_in="2026-03-18T08:00:00Z", clock_out="2026-03-18T16:00:00Z")
        session = validate_success(api.get_session(completed["id"], ADMIN), 200)
        assert session["gross_pay_cents"] == 16000


class TestLastMinuteSurcharge:
    """Corner calculations / estimated_pay_last_minute_surcharge_applied."""

    def test_last_minute_flag_and_surcharge_on_estimate(self, api):
        """PRD §3.5: "It computes whether the booking is last-minute by setting
        `is_last_minute` true when the gap between the `scheduled_start` and the
        confirmation moment is under the last-minute window of 24 hours."
        PRD §3.6: "Starting from that base as the gross, if the booking is
        last-minute the gross is increased by the last-minute surcharge of 15
        percent (the gross is multiplied by 1.15)."

        Clock 2026-03-10T00:00, scheduled 17:00 (17h out < 24h): 3h@2000, 1 child →
        round(6000*1.15) = 6900.

        Design: Corner/calculations/estimated_pay_last_minute_surcharge_applied
        """
        ctx = setup_confirmed_one_time_booking(
            wallet_balance_cents=100000, num_children=1, required_tier="BASIC",
            agreed_rate_cents=2000, confirm_clock="2026-03-10T00:00:00Z",
            scheduled_start="2026-03-10T17:00:00Z", scheduled_end="2026-03-10T20:00:00Z",
            is_holiday=False, email_suffix="lm")
        booking = ctx["booking"]
        assert booking["is_last_minute"] is True, "booking confirmed <24h out is last-minute"
        assert booking["estimated_pay_cents"] == 6900, \
            f"expected estimate 6900 with 15% surcharge, got {booking['estimated_pay_cents']}"
