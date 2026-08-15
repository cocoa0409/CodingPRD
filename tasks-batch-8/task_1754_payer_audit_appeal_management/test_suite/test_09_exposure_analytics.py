"""Computed exposure reads: GROSS vs NET variants, the frozen prior-quarter
snapshot (evaluation order), and the late-submission penalty mode."""
from test_helpers import (
    decide_appeal,
    file_appeal,
    open_appeal,
    setup_case_past_records_deadline,
    setup_determined_case,
    setup_exposure_divergence_scenario,
    submit_records,
    validate_success,
)
from test_helpers import TEST_USERS

READER = TEST_USERS["reader_headers"]


class TestGrossVsNetDivergence:
    def test_gross_reports_unweighted_denied_total(self, api):
        """PRD §3.9: "The GROSS variant is the unweighted sum of those at-risk
        amounts — the full contractual exposure."
        PRD §3.9: "Each claim line contributes an at-risk amount: its
        `denied_amount_cents` when the line is `DENIED`, `PARTIALLY_DENIED`, or
        `FINAL`"

        Design: Difficulty/dual_variant_calc/exposure_gross_vs_net_divergence
        """
        scn = setup_exposure_divergence_scenario()
        exposure = validate_success(
            api.get_exposure(scn["target_case_id"], READER), 200)
        assert exposure["gross_dollars_at_risk_cents"] == 400000
        assert exposure["snapshot_quarter_start"] == "2026-04-01T00:00:00Z", (
            "At 2026-08-01 (Q3) the snapshot window is the prior completed "
            "quarter, Q2")
        assert exposure["gross_dollars_at_risk_cents"] != \
            exposure["net_exposure_cents"], (
            "The variants diverge whenever the snapshot rate is nonzero")

    def test_net_weights_lines_by_frozen_prior_quarter_rate(self, api):
        """PRD §3.9: "The NET variant applies a frozen vindication discount:
        each line's contribution is its at-risk amount multiplied by ten
        thousand minus the line's overturn basis points, divided by ten
        thousand, with each line rounded half up to whole cents before the
        summation."
        PRD §3.9: "A line's overturn basis points come from a frozen snapshot:
        the dollar-weighted success rate described below, computed over appeals
        decided in the prior completed calendar quarter relative to the logical
        now, grouped by the case's payer and the line's issue code."

        Design: Difficulty/dual_variant_calc/exposure_gross_vs_net_divergence
        """
        scn = setup_exposure_divergence_scenario()
        exposure = validate_success(
            api.get_exposure(scn["target_case_id"], READER), 200)
        # Q2 history: 10000 recovered of 110000 appealed -> 909bp frozen rate.
        # NET = round_half_up(400000 * (10000 - 909) / 10000) = 363640.
        assert exposure["net_exposure_cents"] == 363640


class TestFrozenSnapshotEvaluationOrder:
    def _two_denied_lines(self):
        return setup_determined_case(billed_amounts=(400000, 400000))

    def test_default_rate_applies_without_prior_quarter_history(self, api):
        """PRD §3.9: "Lines whose `issue_code_id` is null — auto-denied lines,
        for instance — and payer-issue groups with zero decided appeals in the
        snapshot window both fall back to a default of five thousand basis
        points, i.e. a fifty percent assumed overturn rate."

        Design: Difficulty/combinatorial_formula/net_exposure_frozen_snapshot_evaluation_order
        """
        ctx = self._two_denied_lines()
        exposure = validate_success(
            api.get_exposure(ctx["case"]["id"], READER), 200)
        assert exposure["gross_dollars_at_risk_cents"] == 800000
        assert exposure["net_exposure_cents"] == 400000, (
            "2 lines x round_half_up(400000 * 0.5) at the default 5000bp")

    def test_current_quarter_decision_never_enters_snapshot(self, api):
        """PRD §3.9: "Decisions from the current quarter never feed the
        snapshot, which keeps the exposure figure stable within a quarter and
        breaks the circularity between today's decisions and today's
        exposure."
        PRD §3.9: "Each claim line contributes an at-risk amount: its
        `denied_amount_cents` when the line is `DENIED`, `PARTIALLY_DENIED`, or
        `FINAL`; its full `billed_amount_cents` when the line is still
        `UNDER_AUDIT` on a case whose `late_submission` is true (a late records
        submission puts the entire billed value in jeopardy); and zero in every
        other case."

        Design: Difficulty/combinatorial_formula/net_exposure_frozen_snapshot_evaluation_order
        """
        ctx = self._two_denied_lines()
        line1 = ctx["lines"][0]
        appeal = open_appeal(line1["id"])
        file_appeal(appeal["id"])
        decide_appeal(appeal["id"], ctx["payer"]["id"], "FAVORABLE", 0)
        exposure = validate_success(
            api.get_exposure(ctx["case"]["id"], READER), 200)
        assert exposure["gross_dollars_at_risk_cents"] == 400000, (
            "The OVERTURNED line contributes zero at-risk")
        assert exposure["net_exposure_cents"] == 200000, (
            "The surviving line is still weighted at the FROZEN default "
            "5000bp — the current-quarter FAVORABLE decision is excluded")
        assert exposure["snapshot_quarter_start"] == "2026-04-01T00:00:00Z"


class TestLateSubmissionPenaltyMode:
    def test_late_case_counts_under_audit_lines_at_billed(self, api):
        """PRD §3.9: "its full `billed_amount_cents` when the line is still
        `UNDER_AUDIT` on a case whose `late_submission` is true (a late records
        submission puts the entire billed value in jeopardy)"

        Design: Corner/calculations/exposure_late_submission_counts_under_audit_billed
        """
        scn = setup_case_past_records_deadline((100000, 200000))
        submit_records(scn["case"]["id"], "M-late")
        exposure = validate_success(
            api.get_exposure(scn["case"]["id"], READER), 200)
        assert exposure["late_submission"] is True
        assert exposure["gross_dollars_at_risk_cents"] == 300000, (
            "UNDER_AUDIT lines count at full billed in late mode")
        assert exposure["net_exposure_cents"] == 150000, (
            "Null-issue lines use the default 5000bp snapshot: "
            "round_half_up(100000 * 0.5) + round_half_up(200000 * 0.5)")
