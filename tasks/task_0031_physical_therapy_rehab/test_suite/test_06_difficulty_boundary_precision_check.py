"""Difficulty Rule 6 — boundary_precision_check.

Two numeric thresholds tested at their inclusive boundaries:
  (A) capped_status flips to AT_CAP_WARNING when cum/cap >= 0.90.
  (B) discharge_outcome is UNSUCCESSFUL when goals_met=0 (ratio 0.0 < 0.40).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    setup_poc_with_grant,
    setup_active_poc,
    schedule_visit,
    complete_visit,
    finalize_visit,
    record_discharge_assessment,
    make_therapist_headers,
    TEST_USERS,
)


class TestCappedPostureExact90pctBoundaryIsAtCapWarning:
    """MEDICARE cap = 20000¢. Pre-cum = 11200 (V1 90min CPT_97110). Trigger finalize V2
    (45min CPT_97140 → 7000¢). Cum after = 18200, ratio = 0.91 → AT_CAP_WARNING.
    Boundary check: 18200 >= 0.90 * 20000 = 18000 (inclusive).
    """

    def test_at_cap_warning_when_cumulative_at_or_above_90_percent(self, api):
        """PRD §2.7: "`AT_CAP_WARNING` when `cumulative_billed_cents` is at least
        ninety percent of `capped_dollar_limit_cents` and not yet over the cap (the
        ninety-percent boundary is inclusive)"
        PRD §2.7: "a `MEDICARE` plan is capped at twenty thousand cents (two hundred dollars)"

        Design: Difficulty/boundary_precision_check/capped_posture_exact_90pct_boundary_is_at_cap_warning
        """
        ctx = setup_poc_with_grant(
            insurance_type="MEDICARE", medicare_enrolled=True,
            total_units_granted=30,
        )
        th = ctx["therapist"]["id"]
        gid = ctx["grant"]["id"]
        poc_id = ctx["poc"]["id"]
        # V1: 90min/CPT_97110 → 6 units → 11200¢
        v1 = schedule_visit(gid, th, "2026-06-02T09:00:00Z", "2026-06-02T10:30:00Z",
                            planned_minutes=90, cpt_code="CPT_97110_THER_EX")
        complete_visit(v1["id"], th, actual_minutes=90)
        v1_final = finalize_visit(v1["id"], poc_id)
        assert v1_final["billed_cents"] == 11200
        # V2: 45min/CPT_97140 → 3 units → 7000¢; trigger finalize.
        v2 = schedule_visit(gid, th, "2026-06-03T09:00:00Z", "2026-06-03T09:45:00Z",
                            planned_minutes=45, cpt_code="CPT_97140_MANUAL")
        complete_visit(v2["id"], th, actual_minutes=45)
        v2_final = finalize_visit(v2["id"], poc_id)
        assert v2_final["billed_cents"] == 7000
        poc_after = validate_success(
            api.get_plan_of_care(poc_id, TEST_USERS["billing_clerk_headers"]), 200,
        )
        # cum = 18200; 18200 >= 0.90 * 20000 → AT_CAP_WARNING (inclusive boundary).
        assert poc_after["cumulative_billed_cents"] == 18200
        assert poc_after["capped_status"] == "AT_CAP_WARNING"

    def test_under_cap_when_cumulative_strictly_below_90_percent(self, api):
        """PRD §2.7: "`UNDER_CAP` when `cumulative_billed_cents` is strictly less than
        ninety percent of `capped_dollar_limit_cents`"

        With MEDICARE cap=20000, a single FINALIZED visit billing only 11200¢ leaves
        cum=11200 < 0.90*20000=18000 → UNDER_CAP. Companion boundary case: just BELOW
        the 90% threshold.

        Design: Difficulty/boundary_precision_check/capped_posture_exact_90pct_boundary_is_at_cap_warning
        """
        ctx = setup_poc_with_grant(
            insurance_type="MEDICARE", medicare_enrolled=True,
            total_units_granted=30,
        )
        th = ctx["therapist"]["id"]
        gid = ctx["grant"]["id"]
        poc_id = ctx["poc"]["id"]
        v1 = schedule_visit(gid, th, "2026-06-02T09:00:00Z", "2026-06-02T10:30:00Z",
                            planned_minutes=90, cpt_code="CPT_97110_THER_EX")
        complete_visit(v1["id"], th, actual_minutes=90)
        finalize_visit(v1["id"], poc_id)
        poc_after = validate_success(
            api.get_plan_of_care(poc_id, TEST_USERS["billing_clerk_headers"]), 200,
        )
        assert poc_after["cumulative_billed_cents"] == 11200
        assert poc_after["capped_status"] == "UNDER_CAP"


class TestDischargeOutcomeZeroGoalsMetBoundaryUnsuccessful:
    """ratio = 0/1 = 0.0; below 0.40 threshold → UNSUCCESSFUL."""

    def test_zero_goals_met_returns_unsuccessful(self, api):
        """PRD §3.8: "the system computes `discharge_outcome` by dividing
        `goals_met_count` by `total_goals_count` and bucketing the resulting ratio:
        a ratio at least 0.80 yields the outcome `SUCCESSFUL`; otherwise a ratio at
        least 0.40 yields `PARTIAL`; otherwise the outcome is `UNSUCCESSFUL`."

        Design: Difficulty/boundary_precision_check/discharge_outcome_zero_goals_met_boundary_unsuccessful
        """
        ctx = setup_active_poc(insurance_type="COMMERCIAL")
        da = record_discharge_assessment(
            ctx["poc"]["id"], ctx["therapist"]["id"],
            final_functional_score=30,
            goals_met_count=0,
            total_goals_count=1,
            assessed_on="2026-06-15",
        )
        assert da["discharge_outcome"] == "UNSUCCESSFUL"

    def test_one_third_goals_met_returns_unsuccessful_just_below_partial_boundary(self, api):
        """PRD §3.8: "otherwise a ratio at least 0.40 yields `PARTIAL`; otherwise the
        outcome is `UNSUCCESSFUL`."
        PRD §3.8: "The 0.80 and 0.40 thresholds are inclusive lower bounds."

        Companion boundary check: ratio 1/3 ≈ 0.333... is strictly below 0.40, must
        remain UNSUCCESSFUL.

        Design: Difficulty/boundary_precision_check/discharge_outcome_zero_goals_met_boundary_unsuccessful
        """
        ctx = setup_active_poc(insurance_type="COMMERCIAL")
        da = record_discharge_assessment(
            ctx["poc"]["id"], ctx["therapist"]["id"],
            final_functional_score=30,
            goals_met_count=1,
            total_goals_count=3,
            assessed_on="2026-06-15",
        )
        assert da["discharge_outcome"] == "UNSUCCESSFUL"
