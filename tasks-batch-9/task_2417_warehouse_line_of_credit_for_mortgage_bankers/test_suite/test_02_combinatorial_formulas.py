"""Formulas whose answer depends on the order in which their steps are taken.

Three of them: the circular concentration solve, the per-advance-then-sum fee
accrual, and the four-step effective-rate build-up.
"""

import pytest

from test_helpers import assertions as asserts
from test_helpers import fixtures as fx


# ─── Mode C: the closed-form concentration solve ──────────────────────────────

def _load_three_investors_then_overweight_one():
    """Three wet advances of 2,000,000,000, then a fourth that trips the cap."""
    facility = fx.create_active_facility()
    custodian = fx.register_custodian(facility["id"])

    panel = []
    for name in (
        "Bravo Capital Markets",
        "Charlie Loan Trust",
        "Delta Whole Loan Fund",
    ):
        rating = "B" if name.startswith("Delta") else "A"
        investor = fx.register_investor(
            facility["id"],
            investor_name=name,
            counterparty_rating=rating,
            concentration_limit_pct=0.60,
        )
        commitment = fx.record_commitment(
            facility["id"], investor["id"], committed_amount_cents=5_000_000_000
        )
        panel.append((investor, commitment))

    funded = []
    for index, (_investor, commitment) in enumerate(panel, start=1):
        advance = fx.book_advance(
            facility["id"],
            custodian["id"],
            investor_commitment_id=commitment["id"],
            loan_amount_cents=2_000_000_000,
            funding_type="WET",
        )
        fx.verify_wire(fx.wire_for_advance(advance["id"])["id"], f"CB-00{index}")
        funded.append(fx.fund_advance(advance["id"]))

    overweight = fx.book_advance(
        facility["id"],
        custodian["id"],
        investor_commitment_id=panel[0][1]["id"],
        loan_amount_cents=200_000_000,
        funding_type="WET",
    )
    fx.verify_wire(fx.wire_for_advance(overweight["id"])["id"], "CB-004")
    overweight = fx.fund_advance(overweight["id"])

    return fx.Scenario(
        facility=fx.read_facility(facility["id"]),
        custodian=custodian,
        panel=panel,
        third_advance=funded[2],
        overweight_advance=overweight,
        heaviest_investor=fx.read_investor(panel[0][0]["id"]),
        middle_investor=fx.read_investor(panel[1][0]["id"]),
        heaviest_commitment=fx.read_commitment(panel[0][1]["id"]),
    )


class TestInvestorConcentrationClosedForm:
    def test_solve_returns_the_closed_form_headroom_not_the_provisional(self):
        """The circular constraint is solved, not iterated toward.

        PRD 3.4: "Step seven, reached only when that test fails, computes the
        largest whole-cent amount that would satisfy the constraint: multiply
        the binding cap by the pre-funding outstanding, subtract the pre-funding
        exposure, divide by one minus the binding cap, and floor the quotient to
        whole cents; if the result is negative it is treated as zero."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_c_investor_concentration_closed_form_solve
        """
        scenario = _load_three_investors_then_overweight_one()
        advance = scenario.overweight_advance
        asserts.assert_advance(advance)

        # Stage three sizes the 200,000,000 note at the wet rate of 0.96.
        assert advance["provisional_advance_amount_cents"] == 192_000_000

        # The binding cap is the facility's 0.35, not the investor's 0.60.
        # floor((0.35 * 5,760,000,000 - 1,920,000,000) / 0.65) = 147,692,307.
        assert advance["advance_amount_cents"] == 147_692_307
        assert advance["concentration_capped"] is True
        assert advance["outstanding_balance_cents"] == 147_692_307

        # Measuring the ratio on the pre-funding outstanding instead would have
        # allowed the full provisional amount through.
        assert advance["advance_amount_cents"] < advance[
            "provisional_advance_amount_cents"
        ]

    def test_the_solve_reconciles_exposure_outstanding_and_capacity(self):
        """Everything downstream of the capped amount agrees with it.

        PRD 3.2: "An investor's `exposure_cents` is at all times the sum of
        `outstanding_balance_cents` over the advances whose commitment belongs
        to that investor and whose `funding_status` is `FUNDED` or `SHIPPED`."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_c_investor_concentration_closed_form_solve
        """
        scenario = _load_three_investors_then_overweight_one()

        assert scenario.heaviest_investor["exposure_cents"] == 2_067_692_307
        assert scenario.middle_investor["exposure_cents"] == 1_920_000_000

        assert scenario.facility["outstanding_principal_cents"] == 5_907_692_307
        asserts.assert_availability_projection(scenario.facility)

        commitment = scenario.heaviest_commitment
        assert commitment["allocated_amount_cents"] == 2_067_692_307
        assert commitment["remaining_amount_cents"] == 2_932_307_693
        asserts.assert_commitment_capacity_conserved(commitment)

        summary = fx.read_exposure_summary(scenario.facility["id"])
        asserts.assert_both_conservation_invariants(summary)

    def test_the_third_advance_stays_below_the_de_minimis_floor(self):
        """Under the floor the solve short-circuits and caps nothing.

        PRD 3.4: "Step four short-circuits in two cases: if the advance names no
        commitment there is no investor to concentrate against and the proposed
        principal is returned unchanged; and if the hypothetical post-funding
        outstanding is at or below the de-minimis floor of 5,000,000,000 cents —
        fifty million dollars — the proposed principal is likewise returned
        unchanged, because the test only engages once that figure is strictly
        above the floor."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_c_investor_concentration_closed_form_solve
        """
        scenario = _load_three_investors_then_overweight_one()
        third = scenario.third_advance

        # The third funding takes the line to exactly 5,760,000,000, which is
        # above the floor, but its own investor carries no prior exposure.
        assert third["advance_amount_cents"] == 1_920_000_000
        assert third["provisional_advance_amount_cents"] == 1_920_000_000
        assert third["concentration_capped"] is False


# ─── Mode B: fee accrual rounded per advance, then summed ─────────────────────

def _accrue_ten_days_over_two_wet_advances():
    """Two wet advances at different coupons, then a single ten-day accrual."""
    scenario = fx.setup_facility_panel()
    first = fx.book_advance(
        scenario.facility["id"],
        scenario.custodian["id"],
        investor_commitment_id=scenario.commitment["id"],
        expected_facility_version=scenario.facility_version_before_booking,
        loan_amount_cents=2_000_000_000,
        note_rate=0.0650,
        funding_type="WET",
    )
    fx.verify_wire(fx.wire_for_advance(first["id"])["id"], "CB-101")
    scenario.first_advance = fx.fund_advance(first["id"])

    second = fx.book_advance(
        scenario.facility["id"],
        scenario.custodian["id"],
        investor_commitment_id=scenario.commitment["id"],
        loan_amount_cents=1_000_000_000,
        note_rate=0.0625,
        funding_type="WET",
    )
    fx.verify_wire(fx.wire_for_advance(second["id"])["id"], "CB-102")
    scenario.second_advance = fx.fund_advance(second["id"])

    fx.set_clock("2026-08-11T00:00:00Z")
    scenario.aging_run = fx.run_aging(scenario.facility["id"])
    scenario.facility = fx.read_facility(scenario.facility["id"])
    scenario.first_advance = fx.read_advance(scenario.first_advance["id"])
    return scenario


class TestFeeAccrualRoundingOrder:
    def test_each_advance_rounds_before_the_lines_are_summed(self):
        """Rounding once at the end would be a cent light.

        PRD 3.9: "For each advance of the facility whose `funding_status` is
        `FUNDED` or `SHIPPED`, taken in `created_at` ascending order, the
        interest is that advance's `outstanding_balance_cents` multiplied by the
        sum of its own `note_rate` and the facility spread of 0.0225, divided by
        a day-count basis of 360, multiplied by `accrual_days`, and rounded half
        up to whole cents **for that advance**."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_b_fee_accrual_round_per_advance_then_sum
        """
        scenario = _accrue_ten_days_over_two_wet_advances()
        run = scenario.aging_run
        asserts.assert_aging_run_summary(run)

        assert scenario.facility["outstanding_principal_cents"] == 2_880_000_000
        assert run["accrual_days"] == 10

        # 4,666,667 on the first advance, 2,266,667 on the second and 1,188,889
        # of unused-line fee, each rounded half up on its own line.
        assert run["fee_accrual_cents"] == 8_122_223

        # Summing the three unrounded figures and rounding once yields
        # 8,122,222, which the pinned order deliberately does not produce.
        assert run["fee_accrual_cents"] != 8_122_222

        assert scenario.facility["accrued_fee_balance_cents"] == 8_122_223

        accruals = [
            entry
            for entry in fx.facility_ledger(scenario.facility["id"])
            if entry["entry_type"] == "FEE_ACCRUAL"
        ]
        assert len(accruals) == 1
        asserts.assert_ledger_entry(accruals[0])
        assert accruals[0]["direction"] == "DEBIT"
        assert accruals[0]["amount_cents"] == 8_122_223

    def test_a_ten_day_carry_touches_neither_dwell_nor_margin_calls(self):
        """Fees accrue long before curtailment or a call becomes due.

        PRD 3.6: "`is_aged` is true exactly when `dwell_days` is strictly
        greater than the applicable `dwell_limit_days`."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_b_fee_accrual_round_per_advance_then_sum
        """
        scenario = _accrue_ten_days_over_two_wet_advances()
        run = scenario.aging_run

        assert run["advances_evaluated"] == 2
        assert run["margin_calls_issued"] == 0
        assert run["curtailed_advance_ids"] == []

        assert scenario.first_advance["dwell_days"] == 10
        assert scenario.first_advance["is_aged"] is False

        # The fee posting moves the fee balance only, never the principal.
        assert scenario.facility["outstanding_principal_cents"] == 2_880_000_000
        assert scenario.facility["aged_outstanding_cents"] == 0
        assert scenario.facility["open_margin_call_count"] == 0


# ─── Mode A: the four-step effective-rate chain ───────────────────────────────

def _carry_a_wet_advance_past_two_curtailment_steps():
    """A wet advance whose file never arrives, carried 46 days, then re-marked."""
    scenario = fx.setup_facility_panel()
    advance = fx.book_advance(
        scenario.facility["id"],
        scenario.custodian["id"],
        investor_commitment_id=scenario.commitment["id"],
        expected_facility_version=scenario.facility_version_before_booking,
        funding_type="WET",
    )
    fx.verify_wire(fx.wire_for_advance(advance["id"])["id"], "CB-201")
    scenario.advance = fx.fund_advance(advance["id"])

    fx.set_clock("2026-09-16T00:00:00Z")
    scenario.aging_run = fx.run_aging(scenario.facility["id"])
    scenario.advance = fx.mark_to_market(scenario.advance["id"], 1_950_000_000)
    scenario.facility = fx.read_facility(scenario.facility["id"])
    scenario.calls = fx.advance_margin_calls(scenario.advance["id"])
    return scenario


class TestFourStepEffectiveRateChain:
    def test_the_rate_stacks_the_wet_haircut_on_top_of_two_curtailment_steps(self):
        """Forty-six days of dwell against a thirty-day limit is two full steps.

        PRD 3.6: "When the advance's `dwell_days` is **strictly** greater than
        the rate row's `dwell_limit_days`, the number of curtailment steps is
        the excess of `dwell_days` over `dwell_limit_days`, divided by
        `aging_step_days` and rounded **up** to a whole number; otherwise the
        number of steps is zero."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_a_four_stage_effective_rate_chain
        """
        scenario = _carry_a_wet_advance_past_two_curtailment_steps()
        advance = scenario.advance
        asserts.assert_advance(advance)

        assert advance["dwell_days"] == 46
        assert advance["is_aged"] is True
        # The wet deadline lapsed long before the run reached it.
        assert advance["custody_status"] == "RECEIPT_OVERDUE"

        # 0.98 base, less the 0.02 wet haircut, less two steps of 0.005.
        assert advance["effective_advance_rate"] == pytest.approx(0.95, abs=1e-6)

        assert advance["market_value_cents"] == 1_950_000_000
        # floor(min(2,000,000,000, 1,950,000,000) * 0.95).
        assert advance["eligible_collateral_value_cents"] == 1_852_500_000
        assert advance["outstanding_balance_cents"] == 1_920_000_000
        assert advance["required_paydown_cents"] == 67_500_000

    def test_the_open_call_keeps_its_original_snapshot_after_the_mark_down(self):
        """The obligation is not re-sized underneath a borrower mid-cure.

        PRD 3.6: "If an open call already exists on the advance, the freshly
        recomputed `required_paydown_cents` is still stored on the advance but
        the existing call's `call_amount_cents` is deliberately left at its
        original snapshot — obligations are never silently re-sized underneath a
        borrower who is part-way through curing them."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_a_four_stage_effective_rate_chain
        """
        scenario = _carry_a_wet_advance_past_two_curtailment_steps()

        dwell_calls = [
            call
            for call in scenario.calls
            if call["trigger_reason"] == "DWELL_EXCEEDED"
        ]
        assert len(dwell_calls) == 1
        asserts.assert_margin_call(dwell_calls[0])
        assert dwell_calls[0]["status"] == "ISSUED"
        # The aging run snapshotted 1,920,000,000 less 1,900,000,000.
        assert dwell_calls[0]["call_amount_cents"] == 20_000_000

        # The later mark-down raised the paydown but issued nothing new.
        assert scenario.advance["required_paydown_cents"] == 67_500_000
        assert not [
            call
            for call in scenario.calls
            if call["trigger_reason"] == "VALUATION_DECLINE"
        ]

        assert scenario.facility["status"] == "RESTRICTED"
