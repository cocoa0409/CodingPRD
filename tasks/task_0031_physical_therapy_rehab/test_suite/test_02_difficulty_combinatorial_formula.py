"""Difficulty Rule 2 — combinatorial_formula.

Two PRD calculations combine ≥3 inputs through non-linear caps / nested rounding:
  (A) MIPS composite_score: base + numerator + engagement + improvement,
      each independently capped, sum capped at 100.0.
  (B) Visit billed_cents: per-CPT rate × MPPR (round-per-unit-then-sum).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    setup_active_poc,
    setup_poc_with_grant,
    create_hep,
    create_mips,
    record_initial_evaluation,
    record_re_evaluation,
    schedule_visit,
    complete_visit,
    finalize_visit,
    make_therapist_headers,
)


class TestMipsCompositeScoreNonlinearCapsModeA:
    """MIPS128_FALL_RISK measure: base 60 + numerator 25 + engagement min(10, 2*3.5)=7
    + improvement min(15, 40*0.5)=15 → raw=107 → capped at 100.00.
    """

    def test_composite_score_capped_at_100_when_raw_exceeds(self, api):
        """PRD §3.7: "The four parts are summed, the total is capped at 100.0, and
        the result is rounded half-up to two decimal places and written to `composite_score`."
        PRD §3.7: "The base score is determined by `measure_code`: 60.0 for `MIPS128_FALL_RISK`"
        PRD §3.7: "The numerator bonus adds 25.0 when `numerator_met` is true and 0.0 otherwise."
        PRD §3.7: "The engagement bonus is computed by counting every `HomeExerciseProgram`
        under the same `plan_of_care_id` whose `status` is `ACTIVE` and whose `prescribed_on`
        falls on or after `performance_period_start` and on or before `performance_period_end`,
        multiplying that count by 3.5, then capping the result at a maximum of 10.0."
        PRD §3.7: "the system identifies the `INITIAL` evaluation on the plan and the latest
        evaluation on the plan (ordered by `performed_on` ascending then `created_at`
        ascending, taking the last row), computes the latest evaluation's `functional_score`
        minus the initial evaluation's `functional_score` clamped at zero (so a regression
        contributes zero rather than a negative number), multiplies that improvement by 0.5,
        then caps the result at a maximum of 15.0."

        Design: Difficulty/combinatorial_formula/mips_composite_score_nonlinear_caps_mode_a
        """
        # Build the ctx: MEDICARE Patient + medicare-enrolled Therapist + ACTIVE POC
        # whose INITIAL Eval has functional_score=40 on 2026-06-01.
        ctx = setup_active_poc(
            insurance_type="MEDICARE",
            medicare_enrolled=True,
            functional_score=40,
            certified_start_date="2026-06-01",
            certified_end_date="2026-07-31",
        )
        poc_id = ctx["poc"]["id"]
        th_id = ctx["therapist"]["id"]
        # Two ACTIVE HEPs, both prescribed within 2026-06-01..2026-06-30.
        create_hep(poc_id, th_id, prescribed_on="2026-06-05",
                   exercise_count=5, weekly_frequency=3)
        create_hep(poc_id, th_id, prescribed_on="2026-06-10",
                   exercise_count=6, weekly_frequency=4)
        # RE_EVAL functional_score 80 → improvement 40 → bonus min(15, 20)=15.
        record_re_evaluation(poc_id, th_id, performed_on="2026-06-15",
                             functional_score=80, minutes_spent=25)
        # MIPS128_FALL_RISK measure with numerator_met=true; performance period covers HEPs.
        mips = create_mips(
            ctx["patient"]["id"], poc_id, th_id,
            measure_code="MIPS128_FALL_RISK",
            performance_period_start="2026-06-01",
            performance_period_end="2026-06-30",
            numerator_met=True,
        )
        # Submit: triggers recomputation.
        set_clock("2026-06-20T00:00:00Z")
        submitted = validate_success(
            api.submit_mips_measure(mips["id"], make_therapist_headers(th_id)), 200,
        )
        assert submitted["status"] == "SUBMITTED"
        # base 60 + numerator 25 + engagement min(10, 2*3.5=7)=7 +
        # improvement min(15, 40*0.5=20)=15 → raw=107 → min(100,107)=100.00.
        assert submitted["composite_score"] == pytest.approx(100.00, abs=0.01)

    def test_composite_score_combines_all_four_inputs_at_submit(self, api):
        """PRD §3.7: "The four parts are summed, the total is capped at 100.0, and
        the result is rounded half-up to two decimal places and written to `composite_score`."
        PRD §3.7: "The recomputation runs on every revise and on every submit, so the score
        visible at adjudication is always the score derived from the measure's current inputs
        and the plan's then-current HEP and evaluation rows."

        With MIPS131_PAIN_ASSESSMENT (base 18.0): one ACTIVE HEP in the window
        contributes engagement = min(10, 1*3.5) = 3.5; a RE_EVAL improvement of
        +10 contributes min(15, 10*0.5) = 5; numerator_met=true adds 25. The four
        parts must sum: 18 + 25 + 3.5 + 5 = 51.50 (no cap applies).

        Design: Difficulty/combinatorial_formula/mips_composite_score_nonlinear_caps_mode_a
        """
        ctx = setup_active_poc(
            insurance_type="MEDICARE",
            medicare_enrolled=True,
            functional_score=40,
            certified_start_date="2026-06-01",
            certified_end_date="2026-07-31",
        )
        poc_id = ctx["poc"]["id"]
        th_id = ctx["therapist"]["id"]
        create_hep(poc_id, th_id, prescribed_on="2026-06-05",
                   exercise_count=4, weekly_frequency=3)
        record_re_evaluation(poc_id, th_id, performed_on="2026-06-12",
                             functional_score=50, minutes_spent=25)
        mips = create_mips(
            ctx["patient"]["id"], poc_id, th_id,
            measure_code="MIPS131_PAIN_ASSESSMENT",
            performance_period_start="2026-06-01",
            performance_period_end="2026-06-30",
            numerator_met=True,
        )
        set_clock("2026-06-20T00:00:00Z")
        submitted = validate_success(
            api.submit_mips_measure(mips["id"], make_therapist_headers(th_id)), 200,
        )
        # 18 (base) + 25 (numerator) + min(10, 1*3.5)=3.5 + min(15, 10*0.5)=5 = 51.50
        assert submitted["composite_score"] == pytest.approx(51.50, abs=0.01)


class TestVisitBilledAmountRoundPerUnitThenSumModeB:
    """CPT_97140 at 3500¢/unit, 3 billable units:
       first_unit = 3500
       reduced_per_unit = round_half_up(3500 * 0.5) = 1750
       billed = 3500 + 1750 * 2 = 7000¢
    """

    def test_three_unit_visit_at_cpt_97140_bills_7000_cents(self, api):
        """PRD §3.5: "When the visit has more than one unit, the **multiple-procedure
        payment reduction** applies: the first unit bills at the full per-CPT rate, and
        every unit beyond the first bills at a reduced per-unit rate equal to the CPT
        rate multiplied by one-half. The reduced per-unit rate is rounded half-up to the
        nearest cent **per unit, before** being multiplied by the number of reduced units
        and added to the first unit's full-rate price. The order of operations is fixed:
        round per unit first, then sum."
        PRD §3.5: "Each CPT code has a per-unit rate in cents — `CPT_97110_THER_EX` at
        3200, `CPT_97112_NEURO_REED` at 3900, `CPT_97140_MANUAL` at 3500, `CPT_97530_THER_ACT`
        at 3700."

        Design: Difficulty/combinatorial_formula/visit_billed_amount_round_per_unit_then_sum_mode_b
        """
        ctx = setup_poc_with_grant(
            insurance_type="MEDICARE", medicare_enrolled=True,
            total_units_granted=10,
        )
        v = schedule_visit(
            ctx["grant"]["id"], ctx["therapist"]["id"],
            scheduled_start_utc="2026-06-01T10:00:00Z",
            scheduled_end_utc="2026-06-01T10:45:00Z",
            planned_minutes=45,
            cpt_code="CPT_97140_MANUAL",
        )
        complete_visit(v["id"], ctx["therapist"]["id"], actual_minutes=45)
        finalized = finalize_visit(v["id"], ctx["poc"]["id"])
        assert finalized["status"] == "FINALIZED"
        # Per PRD §3.5: 45 minutes → 23..37 yields 3 units, 38..52 yields 3?
        # Actually 45 falls in 38..52 → 3 units. PRD §3.5 buckets:
        # "under 8 minutes yields 0 units, 8 through 22 yields 1, 23 through 37
        # yields 2, 38 through 52 yields 3, 53 through 67 yields 4". So 45 → 3 units.
        assert finalized["billable_units"] == 3
        assert finalized["billed_cents"] == 7000

    def test_four_unit_visit_at_cpt_97140_bills_8750_cents(self, api):
        """PRD §3.5: "For example, a four-unit visit at `CPT_97140_MANUAL` (rate 3500)
        bills the first unit at 3500 cents, computes a reduced per-unit price of 1750
        cents (half of 3500, no rounding needed), and totals 3500 + 1750 × 3 = 8750 cents."

        Design: Difficulty/combinatorial_formula/visit_billed_amount_round_per_unit_then_sum_mode_b
        """
        # 60 minutes → 53..67 yields 4 units. CPT_97140 at 4 units.
        ctx = setup_poc_with_grant(
            insurance_type="MEDICARE", medicare_enrolled=True,
            total_units_granted=10,
        )
        v = schedule_visit(
            ctx["grant"]["id"], ctx["therapist"]["id"],
            scheduled_start_utc="2026-06-01T10:00:00Z",
            scheduled_end_utc="2026-06-01T11:00:00Z",
            planned_minutes=60,
            cpt_code="CPT_97140_MANUAL",
        )
        complete_visit(v["id"], ctx["therapist"]["id"], actual_minutes=60)
        finalized = finalize_visit(v["id"], ctx["poc"]["id"])
        assert finalized["billable_units"] == 4
        assert finalized["billed_cents"] == 8750
