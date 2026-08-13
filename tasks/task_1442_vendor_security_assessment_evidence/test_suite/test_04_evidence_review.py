"""Evidence artifacts and the evidence review: coverage gaps, window variants,
score aggregation, and the composite (PRD §3.5, §3.7)."""
import pytest

from test_helpers import (
    ANALYST,
    ApiErrorId,
    assert_evidence_artifact,
    assert_score,
    contact_headers,
    create_evidence_payload,
    create_exception_payload,
    get_cycle_artifact,
    get_cycle_response,
    get_success_data,
    review_artifact_clean,
    setup_evidence_review_cycle,
    setup_scored_cycle,
    upload_evidence,
    validate_error,
    validate_success,
)

# Artifact covering 2025-02-02..2026-02-02: exactly 180 days before the default
# issuance instant 2026-08-01T00:00:00Z.
GAP_180_EVIDENCE = {"period_start": "2025-02-02T00:00:00Z", "period_end": "2026-02-02T00:00:00Z"}
GAP_181_EVIDENCE = {"period_start": "2025-02-01T00:00:00Z", "period_end": "2026-02-01T00:00:00Z"}
# SOC2 artifact at the exact 180-day completion ceiling (PRD §3.5 forbids
# completing review beyond it): at TIER_3's strict window this yields the full
# 30-point penalty, i.e. a 100 - 30 = 70 contribution.
GAP_MAX_SOC2_EVIDENCE = {"kind": "SOC2_TYPE2", "period_start": "2025-02-02T00:00:00Z", "period_end": "2026-02-02T00:00:00Z"}
FRESH_ISO_EVIDENCE = {"kind": "ISO27001", "period_start": "2025-08-01T00:00:00Z", "period_end": "2026-08-01T00:00:00Z", "issued_by": "CertBody"}


class TestStandardVsStrictWindow:
    def test_tier1_artifact_uses_365_day_normalisation(self, api):
        """PRD §3.5: "for cycles issued at `TIER_1` or `TIER_2`, the penalty is the
        gap in days capped at 365, divided by 365, multiplied by 30; for the stricter
        `TIER_3` and `TIER_4` cycles, the gap is capped at 180 and divided by 180
        instead, making the penalty climb twice as steeply."

        gap 180 under the standard window: 100 - 180/365*30 = 85.2054... -> 85.21.

        Design: Difficulty/dual_variant_calc/evidence_score_standard_vs_strict_window
        """
        ctx = setup_evidence_review_cycle(tier="TIER_1", evidence_overrides=GAP_180_EVIDENCE)
        artifact = review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], ctx["artifact"]["id"])
        assert artifact["coverage_gap_days"] == 180
        cycle = validate_success(
            api.complete_evidence_review(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST), 200
        )
        assert_score(cycle["evidence_score"], 85.21)

    def test_tier3_artifact_uses_180_day_normalisation(self, api):
        """PRD §3.5: "for cycles issued at `TIER_1` or `TIER_2`, the penalty is the
        gap in days capped at 365, divided by 365, multiplied by 30; for the stricter
        `TIER_3` and `TIER_4` cycles, the gap is capped at 180 and divided by 180
        instead, making the penalty climb twice as steeply."

        The identical artifact at TIER_3: 100 - min(180,180)/180*30 = 70.0.

        Design: Difficulty/dual_variant_calc/evidence_score_standard_vs_strict_window
        """
        ctx = setup_evidence_review_cycle(tier="TIER_3", evidence_overrides=GAP_180_EVIDENCE)
        artifact = review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], ctx["artifact"]["id"])
        assert artifact["coverage_gap_days"] == 180
        cycle = validate_success(
            api.complete_evidence_review(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST), 200
        )
        assert_score(cycle["evidence_score"], 70.0)


class TestEvidenceScoreMultiInput:
    def test_gap_penalty_and_severity_deduction_combine(self, api):
        """PRD §3.5: "Each contributing artifact starts from a base by kind — 100 for
        `SOC2_TYPE2`, 95 for `ISO27001`, 80 for `SOC2_TYPE1`, 70 for `PENTEST`, 50
        for `OTHER` — and loses a coverage-gap penalty of up to 30 points".
        PRD §3.5: "then the platform subtracts severity deductions for the cycle's
        `EVIDENCE`-source exceptions still in `OPEN` or `IN_REMEDIATION` — 25 per
        `CRITICAL`, 15 per `HIGH`, 8 per `MEDIUM`, and 3 per `LOW` — and the cycle's
        `evidence_score` is the result rounded half-up to two decimal places, never
        allowed below zero."
        PRD §3.5: "With `open_exception_count` greater than zero, the cycle moves
        `EVIDENCE_REVIEW → REMEDIATION`, the composite score is computed, and any
        required contract addendum is generated (§3.7)."

        avg((100-30), (95-0)) = 82.5 minus HIGH 15 -> 67.5.

        TIER_3 so the strict 180-day window yields the full 30-point penalty on
        a gap-180 SOC2 artifact (100 - min(180,180)/180*30 = 70); a gap beyond
        180 days could never complete review per PRD §3.5.

        Design: Difficulty/combinatorial_formula/evidence_score_multi_input_tiered_mode_a
        """
        ctx = setup_scored_cycle(tier="TIER_3")
        e1 = upload_evidence(ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), **GAP_MAX_SOC2_EVIDENCE)
        e2 = upload_evidence(ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), **FRESH_ISO_EVIDENCE)
        review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], e1["id"])
        review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], e2["id"])
        get_success_data(
            api.create_exception(
                ctx["vendor"]["id"], ctx["cycle"]["id"],
                create_exception_payload(severity="HIGH", description="gap in change mgmt",
                                         evidence_artifact_id=e1["id"]),
                ANALYST,
            )
        )
        cycle = validate_success(
            api.complete_evidence_review(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST), 200
        )
        assert cycle["status"] == "REMEDIATION"
        assert_score(cycle["evidence_score"], 67.5)

    def test_without_exceptions_clean_pass_approves(self, api):
        """PRD §3.5: "The clean pass moves the cycle `EVIDENCE_REVIEW → APPROVED`
        outright, but only when every artifact is `REVIEWED_CLEAN`, no exception
        remains open, the composite meets or exceeds the tier pass threshold (a
        shortfall on this clean-approval path is rejected with
        `ERR_SCORE_BELOW_THRESHOLD`, HTTP 422), and no `REQUIRED` or `DRAFTED`
        addendum is outstanding".

        Same two artifacts, zero exceptions: avg(70, 95) = 82.5, composite
        0.4*100 + 0.6*82.5 = 89.5 >= 80 (TIER_3 threshold) -> APPROVED.

        Design: Difficulty/combinatorial_formula/evidence_score_multi_input_tiered_mode_a
        """
        ctx = setup_scored_cycle(tier="TIER_3")
        e1 = upload_evidence(ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), **GAP_MAX_SOC2_EVIDENCE)
        e2 = upload_evidence(ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), **FRESH_ISO_EVIDENCE)
        review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], e1["id"])
        review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], e2["id"])
        cycle = validate_success(
            api.complete_evidence_review(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST), 200
        )
        assert cycle["status"] == "APPROVED"
        assert_score(cycle["evidence_score"], 82.5)
        vendor = get_success_data(api.get_vendor(ctx["vendor"]["id"], ANALYST))
        assert vendor["posture"] == "APPROVED"


class TestCoverageGapBoundary:
    def test_gap_exactly_180_completes_clean(self, api):
        """PRD §3.5: "Completing a review on an artifact whose gap exceeds 180 days
        likewise fails coverage validity with `ERR_EVIDENCE_COVERAGE_INVALID`."
        PRD §3.5: "Either exit computes the artifact's `coverage_gap_days` — the
        whole days between its `period_end` and the cycle's `issued_at`."

        180 does not exceed 180, so the review completes.

        Design: Difficulty/boundary_precision_check/evidence_coverage_gap_180_day_cliff
        """
        ctx = setup_evidence_review_cycle(evidence_overrides=GAP_180_EVIDENCE)
        artifact = review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], ctx["artifact"]["id"])
        assert_evidence_artifact(artifact)
        assert artifact["coverage_gap_days"] == 180
        assert artifact["status"] == "REVIEWED_CLEAN"

    def test_gap_181_fails_coverage_validity(self, api):
        """PRD §3.5: "Completing a review on an artifact whose gap exceeds 180 days
        likewise fails coverage validity with `ERR_EVIDENCE_COVERAGE_INVALID`."

        Design: Difficulty/boundary_precision_check/evidence_coverage_gap_180_day_cliff
        """
        ctx = setup_evidence_review_cycle(evidence_overrides=GAP_181_EVIDENCE)
        get_success_data(
            api.start_evidence_review(ctx["vendor"]["id"], ctx["cycle"]["id"], ctx["artifact"]["id"], ANALYST)
        )
        res = api.complete_artifact_review(ctx["vendor"]["id"], ctx["cycle"]["id"], ctx["artifact"]["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_EVIDENCE_COVERAGE_INVALID)
        artifact = get_cycle_artifact(ctx["cycle"]["id"], ctx["artifact"]["id"])
        assert artifact["status"] == "UNDER_REVIEW"


class TestCoverageGapIntervalSemantics:
    def test_period_end_on_issuance_day_yields_zero_gap(self, api):
        """PRD §3.5: "Either exit computes the artifact's `coverage_gap_days` — the
        whole days between its `period_end` and the cycle's `issued_at`."

        period_end == issued_at day -> gap 0; the artifact completes clean.

        Design: Difficulty/resource_temporal_overlap/evidence_coverage_gap_vs_issued_at_interval
        """
        ctx = setup_evidence_review_cycle()  # default window ends 2026-08-01, issued 2026-08-01
        artifact = review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], ctx["artifact"]["id"])
        assert artifact["coverage_gap_days"] == 0
        assert artifact["status"] == "REVIEWED_CLEAN"

    def test_partial_year_gap_counted_in_whole_days(self, api):
        """PRD §3.5: "Either exit computes the artifact's `coverage_gap_days` — the
        whole days between its `period_end` and the cycle's `issued_at`."

        period_end 2026-04-01 -> issued 2026-08-01 = 122 whole days, still within
        the 180-day ceiling.

        Design: Difficulty/resource_temporal_overlap/evidence_coverage_gap_vs_issued_at_interval
        """
        ctx = setup_evidence_review_cycle(
            evidence_overrides={"period_start": "2026-01-01T00:00:00Z", "period_end": "2026-04-01T00:00:00Z"}
        )
        artifact = review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], ctx["artifact"]["id"])
        assert artifact["coverage_gap_days"] == 122
        assert artifact["status"] == "REVIEWED_CLEAN"


class TestCompositeScore:
    def test_composite_is_forty_sixty_weighted(self, api):
        """PRD §3.7: "Two component scores roll up into the cycle's
        `composite_score`: forty percent of `questionnaire_score` plus sixty percent
        of `evidence_score`, rounded half-up to two decimal places, computed only
        when both components are present."

        questionnaire 100.0 (single YES item, no revisions) and evidence 67.5
        (SOC2 gap 180 at TIER_3's strict window -> 70, plus ISO clean at 95,
        one open HIGH) -> 0.4*100 + 0.6*67.5 = 80.5.

        Design: Corner/calculations/composite_score_weighted_40_60
        """
        ctx = setup_scored_cycle(tier="TIER_3")
        e1 = upload_evidence(ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), **GAP_MAX_SOC2_EVIDENCE)
        e2 = upload_evidence(ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), **FRESH_ISO_EVIDENCE)
        review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], e1["id"])
        review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], e2["id"])
        get_success_data(
            api.create_exception(
                ctx["vendor"]["id"], ctx["cycle"]["id"],
                create_exception_payload(severity="HIGH", evidence_artifact_id=e1["id"]),
                ANALYST,
            )
        )
        cycle = validate_success(
            api.complete_evidence_review(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST), 200
        )
        assert_score(cycle["questionnaire_score"], 100.0)
        assert_score(cycle["evidence_score"], 67.5)
        assert_score(cycle["composite_score"], 80.5)  # 0.40*100 + 0.60*67.5

    def test_rejected_artifacts_excluded_from_average(self, api):
        """PRD §3.5: "Only artifacts in `REVIEWED_CLEAN` or `REVIEWED_WITH_EXCEPTIONS`
        contribute; `REJECTED` artifacts are excluded from the average entirely, and
        if none qualify the evidence score is 0.0."
        PRD §3.5: "An artifact can instead be rejected outright: rejecting is
        warranted when `coverage_gap_days` exceeds 180 days or when the coverage
        window is invalid, and it moves the artifact to `REJECTED` while
        auto-creating an `ExceptionFinding` with `source` `EVIDENCE`, severity
        `HIGH`, a generated `description` capturing the rejection rationale, and
        status `OPEN`".

        Only the ISO artifact counts: 95 minus the auto-created HIGH exception's
        15-point deduction -> 80.0.

        Design: Corner/calculations/composite_score_input_set_filtering
        """
        ctx = setup_scored_cycle()
        e1 = upload_evidence(ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx), **FRESH_ISO_EVIDENCE)
        e2 = upload_evidence(
            ctx["vendor"]["id"], ctx["cycle"]["id"], contact_headers(ctx),
            kind="OTHER", period_start="2024-01-01T00:00:00Z", period_end="2025-01-01T00:00:00Z",
            issued_by="Self",
        )
        get_success_data(api.start_evidence_review(ctx["vendor"]["id"], ctx["cycle"]["id"], e1["id"], ANALYST))
        get_success_data(api.start_evidence_review(ctx["vendor"]["id"], ctx["cycle"]["id"], e2["id"], ANALYST))
        get_success_data(api.complete_artifact_review(ctx["vendor"]["id"], ctx["cycle"]["id"], e1["id"], ANALYST))
        # gap 577 > 180 -> reject is warranted; auto-creates a HIGH OPEN exception.
        rejected = get_success_data(api.reject_evidence(ctx["vendor"]["id"], ctx["cycle"]["id"], e2["id"], ANALYST))
        assert rejected["status"] == "REJECTED"
        cycle = validate_success(
            api.complete_evidence_review(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST), 200
        )
        assert_score(cycle["evidence_score"], 80.0)
        assert cycle["status"] == "REMEDIATION"


class TestEvidenceReviewGates:
    def test_complete_with_pending_artifact_rejected(self, api):
        """PRD §3.5: "When every artifact for the cycle has reached `REVIEWED_CLEAN`,
        `REVIEWED_WITH_EXCEPTIONS`, or `REJECTED` — completing earlier is rejected
        with `ERR_EVIDENCE_PENDING_REVIEW` (HTTP 422)".

        Design: Corner/validations/evidence_review_complete_with_pending_artifact_rejected
        """
        ctx = setup_evidence_review_cycle()  # artifact still RECEIVED
        res = api.complete_evidence_review(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_EVIDENCE_PENDING_REVIEW)

    def test_upload_with_inverted_period_rejected(self, api):
        """PRD §3.5: "A `period_end` that does not fall after `period_start` is
        rejected at upload with `ERR_EVIDENCE_COVERAGE_INVALID` (HTTP 422)."

        Design: Corner/validations/evidence_invalid_period_rejected
        """
        ctx = setup_scored_cycle()
        res = api.upload_evidence(
            ctx["vendor"]["id"], ctx["cycle"]["id"],
            create_evidence_payload(period_start="2026-08-01T00:00:00Z", period_end="2025-08-01T00:00:00Z"),
            contact_headers(ctx),
        )
        validate_error(res, ApiErrorId.ERR_EVIDENCE_COVERAGE_INVALID)


class TestImmediateConsistency:
    def test_scores_present_in_completion_response(self, api):
        """PRD §3.5: "When every artifact for the cycle has reached `REVIEWED_CLEAN`,
        `REVIEWED_WITH_EXCEPTIONS`, or `REJECTED` — completing earlier is rejected
        with `ERR_EVIDENCE_PENDING_REVIEW` (HTTP 422) — the analyst completes the
        evidence review, and the platform computes the cycle's `evidence_score`."
        PRD §3.7: "Two component scores roll up into the cycle's `composite_score`:
        forty percent of `questionnaire_score` plus sixty percent of
        `evidence_score`, rounded half-up to two decimal places, computed only when
        both components are present."

        Clean ISO27001: evidence 95.0 and composite 0.4*100 + 0.6*95 = 97.0 are
        populated on the very response that completes the review, and the cycle
        transitions straight to APPROVED.

        Design: Corner/consistency_model/immediate_consistency_cycle_scores_visible_in_response
        """
        ctx = setup_evidence_review_cycle(evidence_overrides=FRESH_ISO_EVIDENCE)
        review_artifact_clean(ctx["vendor"]["id"], ctx["cycle"]["id"], ctx["artifact"]["id"])
        cycle = validate_success(
            api.complete_evidence_review(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST), 200
        )
        assert_score(cycle["evidence_score"], 95.0)
        assert_score(cycle["composite_score"], 97.0)
        assert cycle["status"] == "APPROVED"
        vendor = get_success_data(api.get_vendor(ctx["vendor"]["id"], ANALYST))
        assert vendor["posture"] == "APPROVED"
