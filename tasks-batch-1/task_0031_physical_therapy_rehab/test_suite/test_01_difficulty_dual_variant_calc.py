"""Difficulty Rule 1 — dual_variant_calc.

Two forecasted-vs-actual calculations diverge when their inputs disagree:
  (A) Visit.planned_units (forward-looking) vs Visit.billable_units (chronological)
  (B) MIPSQualityMeasure.composite_score under DRAFT revise vs at SUBMIT
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    setup_completed_visit,
    setup_active_poc,
    create_mips,
    make_therapist_headers,
    TEST_USERS,
    revise_mips_payload,
)


class TestVisitPlannedVsBillableUnitsDivergeOnOverrun:
    """A 60-minute planned visit reserves 4 forward-looking units; an actual
    30-minute delivery resolves to 2 chronological units — the gap proves the
    two variants are computed independently and diverge when forecasts overrun.
    """

    def test_planned_units_pinned_at_schedule_to_4(self, api):
        """PRD §3.5: "At schedule time the system pre-computes `planned_units` — the
        forward-looking reservation against the grant — by running the eight-minute rule
        on `planned_minutes`."
        PRD §3.5: "53 through 67 yields 4"

        Design: Difficulty/dual_variant_calc/visit_planned_vs_billable_units_diverge_on_overrun
        """
        # Schedule a 60-minute visit; per the 8-minute rule on planned_minutes,
        # 53 through 67 yields 4 → planned_units == 4.
        ctx = setup_completed_visit(
            planned_minutes=60,
            actual_minutes=30,
            scheduled_start_utc="2026-06-02T09:00:00Z",
            scheduled_end_utc="2026-06-02T10:00:00Z",
            cpt_code="CPT_97110_THER_EX",
        )
        v = ctx["visit"]
        assert v["planned_units"] == 4, \
            f"planned_units should be 4 for planned_minutes=60, got {v['planned_units']}"

    def test_billable_units_recomputed_at_complete_from_actual_minutes(self, api):
        """PRD §3.5: "On success the visit's `billable_units` is recomputed from
        `actual_minutes` using the chronological variant of the eight-minute rule — same
        buckets as the planned-units calculation, but operating on actually-delivered
        minutes rather than a forecast."
        PRD §3.5: "23 through 37 yields 2"

        Design: Difficulty/dual_variant_calc/visit_planned_vs_billable_units_diverge_on_overrun
        """
        ctx = setup_completed_visit(
            planned_minutes=60,
            actual_minutes=30,
            scheduled_start_utc="2026-06-02T09:00:00Z",
            scheduled_end_utc="2026-06-02T10:00:00Z",
            cpt_code="CPT_97110_THER_EX",
        )
        v = ctx["visit"]
        assert v["billable_units"] == 2, \
            f"billable_units should be 2 for actual_minutes=30, got {v['billable_units']}"

    def test_planned_units_diverges_from_billable_units_after_overrun(self, api):
        """PRD §3.5: "The two variants will agree when `actual_minutes` equals
        `planned_minutes` and may diverge otherwise: a visit planned for 60 minutes
        reserves four units at schedule time, but if only 30 minutes are actually
        delivered, `billable_units` resolves to two."

        Design: Difficulty/dual_variant_calc/visit_planned_vs_billable_units_diverge_on_overrun
        """
        ctx = setup_completed_visit(
            planned_minutes=60,
            actual_minutes=30,
            scheduled_start_utc="2026-06-02T09:00:00Z",
            scheduled_end_utc="2026-06-02T10:00:00Z",
            cpt_code="CPT_97110_THER_EX",
        )
        v = ctx["visit"]
        assert v["planned_units"] == 4
        assert v["billable_units"] == 2
        assert v["planned_units"] != v["billable_units"]


class TestMipsScoreDivergesBetweenReviseAndSubmit:
    """A MIPS128 DRAFT measure has numerator_met flipped via revise. Two computation
    moments produce two scores: base-only 60.00 vs base+numerator 85.00.
    """

    def test_score_after_revise_with_numerator_false_is_60(self, api):
        """PRD §3.7: "Revising recomputes `composite_score` and increments the
        measure's `version`."
        PRD §3.7: "The base score is determined by `measure_code`: 60.0 for `MIPS128_FALL_RISK`"
        PRD §3.7: "The numerator bonus adds 25.0 when `numerator_met` is true and 0.0 otherwise."

        Design: Difficulty/dual_variant_calc/mips_score_diverges_between_revise_and_submit
        """
        ctx = setup_active_poc(
            insurance_type="MEDICARE", medicare_enrolled=True,
            functional_score=50,
        )
        th_headers = make_therapist_headers(ctx["therapist"]["id"])
        mips = create_mips(
            ctx["patient"]["id"], ctx["poc"]["id"], ctx["therapist"]["id"],
            measure_code="MIPS128_FALL_RISK", numerator_met=False,
        )
        # Revise — recomputes composite_score with numerator_met=false.
        res = api.revise_mips_measure(
            mips["id"], revise_mips_payload(numerator_met=False), th_headers,
        )
        revised = validate_success(res, 200)
        # base=60, numerator_bonus=0, engagement=0 (no HEPs), improvement=0 (no RE_EVAL)
        # raw = 60 → min(100, 60) → 60.00
        assert revised["composite_score"] == pytest.approx(60.00, abs=0.01)

    def test_score_at_submit_with_numerator_true_is_85(self, api):
        """PRD §3.7: "The same `Therapist` may submit the measure (transition
        `DRAFT → SUBMITTED`); submit is allowed only when the parent plan's `status`
        is one of `ACTIVE`, `RECERT_DUE`, `DISCHARGED`, and it triggers a recomputation
        of `composite_score`."
        PRD §3.7: "The numerator bonus adds 25.0 when `numerator_met` is true and 0.0 otherwise."

        Design: Difficulty/dual_variant_calc/mips_score_diverges_between_revise_and_submit
        """
        ctx = setup_active_poc(
            insurance_type="MEDICARE", medicare_enrolled=True,
            functional_score=50,
        )
        th_headers = make_therapist_headers(ctx["therapist"]["id"])
        mips = create_mips(
            ctx["patient"]["id"], ctx["poc"]["id"], ctx["therapist"]["id"],
            measure_code="MIPS128_FALL_RISK", numerator_met=False,
        )
        # Flip numerator_met=true via revise, then submit.
        api.revise_mips_measure(mips["id"], revise_mips_payload(numerator_met=True), th_headers)
        submitted = validate_success(
            api.submit_mips_measure(mips["id"], th_headers), 200,
        )
        # base 60 + numerator 25 + engagement 0 + improvement 0 = 85 → min(100,85)=85.00
        assert submitted["status"] == "SUBMITTED"
        assert submitted["composite_score"] == pytest.approx(85.00, abs=0.01)
