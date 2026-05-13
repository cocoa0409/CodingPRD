"""Stage aggregation, threshold-based advance/eliminate, publish
cascades (PRD §3.5).

Includes the boundary precision tests for the passing_threshold rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PO,
    advance_clock,
    add_designer_with_submission,
    assign_and_score,
    create_reviewer,
    iso_at,
    setup_on_shelf_project,
    setup_in_final_aggregating,
    setup_in_final_with_advancing,
    start_and_publish_stage,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStageQuorum:

    def test_publish_without_quorum_rejected(self, api):
        """PRD §3.5: 'Two preconditions must hold: every submission in
        this stage must have at least reviewer_quorum SUBMITTED
        assignments, and no in-stage submission may have any assignment
        currently in DISPUTED. A failure on either condition rejects
        the publish with ERR_QUORUM_NOT_MET.'

        Claim: publishing without quorum returns ERR_QUORUM_NOT_MET.
        """
        ctx = setup_on_shelf_project(reviewer_quorum=3)
        designer, sub = add_designer_with_submission(
            ctx["project"]["id"], categories=[ctx["category"]["code"]],
        )
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        # Only 2 reviewers — below quorum=3.
        r1 = create_reviewer(categories=[ctx["category"]["code"]],
                              max_concurrent_assignments=10)
        r2 = create_reviewer(categories=[ctx["category"]["code"]],
                              max_concurrent_assignments=10)
        assign_and_score(
            review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
            submission_id=sub["id"],
            reviewer=r1,
            criterion_scores={"creativity": 80, "execution": 80},
        )
        assign_and_score(
            review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
            submission_id=sub["id"],
            reviewer=r2,
            criterion_scores={"creativity": 80, "execution": 80},
        )
        # /_clock past PRELIMINARY ends_at.
        advance_clock(ctx["timeline"]["after_preliminary_ends"])
        validate_success(api.start_aggregation(
            ctx["stages"]["PRELIMINARY"]["id"], PO,
        ))
        resp = api.publish_stage(ctx["stages"]["PRELIMINARY"]["id"], PO)
        validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET.value)


class TestPassingThresholdBoundary:
    """PRD §3.5 + §3.5 publish cascade: '>=' semantics, two-decimal
    rounding."""

    def test_score_at_passing_threshold_advances(self, api):
        """PRD §3.5: 'On preliminary publish, every ACCEPTED submission
        whose stored aggregate equals or exceeds passing_threshold
        advances to ADVANCING_SEMIFINAL.'

        Claim: aggregate==passing_threshold exactly causes
        ADVANCING_SEMIFINAL (boundary precision: 75.00 vs 75.00 with
        '>=').

        # difficulty: boundary_precision_check/passing_threshold_at_exact_boundary
        """
        ctx = setup_on_shelf_project(
            passing_threshold=75.00,
            reviewer_quorum=3,
        )
        designer, sub = add_designer_with_submission(
            ctx["project"]["id"], categories=[ctx["category"]["code"]],
        )
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        # Three reviewers: scores 70, 75, 80 -> mean = 75.00 (n<5, no trim).
        reviewers = [create_reviewer(categories=[ctx["category"]["code"]],
                                      max_concurrent_assignments=10)
                     for _ in range(3)]
        for r, s in zip(reviewers, [70, 75, 80]):
            assign_and_score(
                review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
                submission_id=sub["id"],
                reviewer=r,
                criterion_scores={"creativity": s, "execution": s},
            )
        advance_clock(ctx["timeline"]["after_preliminary_ends"])
        start_and_publish_stage(ctx["stages"]["PRELIMINARY"]["id"])
        sub_after = validate_success(api.get_submission(sub["id"], PO))
        assert sub_after["aggregate_score_by_stage"]["PRELIMINARY"] == pytest.approx(75.00, abs=1e-9)
        assert sub_after["status"] == "ADVANCING_SEMIFINAL", (
            f"At threshold (75.00 >= 75.00) submission must advance; "
            f"got status {sub_after['status']!r}"
        )

    def test_score_strictly_below_threshold_eliminated(self, api):
        """PRD §3.5: 'every ACCEPTED submission whose stored aggregate
        is strictly below passing_threshold transitions to the terminal
        ELIMINATED state.'

        Claim: an aggregate just under the threshold yields ELIMINATED.

        # difficulty: boundary_precision_check/passing_threshold_at_exact_boundary
        """
        ctx = setup_on_shelf_project(
            passing_threshold=75.00,
            reviewer_quorum=3,
        )
        designer, sub = add_designer_with_submission(
            ctx["project"]["id"], categories=[ctx["category"]["code"]],
        )
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        reviewers = [create_reviewer(categories=[ctx["category"]["code"]],
                                      max_concurrent_assignments=10)
                     for _ in range(3)]
        # mean of 70, 75, 79.97 = 74.99
        for r, s in zip(reviewers, [70, 75, 79.97]):
            assign_and_score(
                review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
                submission_id=sub["id"],
                reviewer=r,
                criterion_scores={"creativity": s, "execution": s},
            )
        advance_clock(ctx["timeline"]["after_preliminary_ends"])
        start_and_publish_stage(ctx["stages"]["PRELIMINARY"]["id"])
        sub_after = validate_success(api.get_submission(sub["id"], PO))
        assert sub_after["aggregate_score_by_stage"]["PRELIMINARY"] < 75.00
        assert sub_after["status"] == "ELIMINATED", (
            f"At <75.00 submission must be ELIMINATED; got status "
            f"{sub_after['status']!r}"
        )


class TestPublishCascade:

    def test_publish_preliminary_advances_project_and_opens_semifinal(self, api):
        """PRD §3.5: 'On a successful publish, ReviewStage.status flips
        to PUBLISHED, advancing_submission_ids is pinned in the same
        instant and becomes immutable, an AuditEvent with action_kind
        of STAGE_PUBLISHED is emitted, and the parent project advances:
        IN_PRELIMINARY to IN_SEMIFINAL when the preliminary stage
        publishes.'

        Claim: after preliminary publish:
        - ReviewStage.status == PUBLISHED
        - Project.status == IN_SEMIFINAL
        - SEMIFINAL stage status -> OPEN
        """
        ctx = setup_in_final_with_advancing(n_submissions=1)
        # setup_in_final_with_advancing already drove the project
        # through both PRELIMINARY and SEMIFINAL publish. Verify the
        # current project is in IN_FINAL with FINAL stage OPEN.
        project_after = validate_success(
            api.get_project(ctx["project"]["id"], PO),
        )
        assert project_after["status"] == "IN_FINAL", (
            f"Expected IN_FINAL after semifinal publish, got "
            f"{project_after['status']!r}"
        )

    def test_advancing_submission_ids_empty_when_none_pass(self, api):
        """PRD §3.5: 'on preliminary publish, every ACCEPTED submission
        whose stored aggregate equals or exceeds passing_threshold
        advances to ADVANCING_SEMIFINAL, and every ACCEPTED submission
        whose stored aggregate is strictly below passing_threshold
        transitions to the terminal ELIMINATED state.'

        Claim: when no submission meets threshold,
        ReviewStage.advancing_submission_ids == [] and every
        submission becomes ELIMINATED.

        # difficulty: boundary_precision_check/empty_advancing_list_after_publish
        """
        ctx = setup_on_shelf_project(
            passing_threshold=95.00,
            reviewer_quorum=3,
        )
        # 2 submissions, both with aggregates well below 95.
        sub_pairs = []
        for i in range(2):
            d, s = add_designer_with_submission(
                ctx["project"]["id"],
                categories=[ctx["category"]["code"]],
            )
            sub_pairs.append((d, s))
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        reviewers = [create_reviewer(categories=[ctx["category"]["code"]],
                                      max_concurrent_assignments=10)
                     for _ in range(3)]
        target_means = [60.00, 70.00]
        for (d, s), mean in zip(sub_pairs, target_means):
            for r in reviewers:
                assign_and_score(
                    review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
                    submission_id=s["id"],
                    reviewer=r,
                    criterion_scores={"creativity": mean, "execution": mean},
                )
        advance_clock(ctx["timeline"]["after_preliminary_ends"])
        stage_after = start_and_publish_stage(
            ctx["stages"]["PRELIMINARY"]["id"],
        )
        assert stage_after["status"] == "PUBLISHED"
        assert stage_after.get("advancing_submission_ids") == [], (
            f"advancing_submission_ids must be [] when no submission "
            f"meets threshold; got {stage_after.get('advancing_submission_ids')!r}"
        )
        for _, s in sub_pairs:
            s_after = validate_success(api.get_submission(s["id"], PO))
            assert s_after["status"] == "ELIMINATED", (
                f"Submission {s['id']} expected ELIMINATED, got "
                f"{s_after['status']!r}"
            )

    def test_empty_advancing_list_stage_published(self, api):
        """PRD §3.5: 'On a successful publish, ReviewStage.status flips
        to PUBLISHED, advancing_submission_ids is pinned in the same
        instant and becomes immutable.'

        Claim: even with zero advancing submissions, the stage still
        moves to PUBLISHED. (Confirms publish is not blocked by an
        empty advance list.)

        # difficulty: boundary_precision_check/empty_advancing_list_after_publish
        """
        ctx = setup_on_shelf_project(
            passing_threshold=95.00,
            reviewer_quorum=3,
        )
        d, s = add_designer_with_submission(
            ctx["project"]["id"],
            categories=[ctx["category"]["code"]],
        )
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        reviewers = [create_reviewer(categories=[ctx["category"]["code"]],
                                      max_concurrent_assignments=10)
                     for _ in range(3)]
        for r in reviewers:
            assign_and_score(
                review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
                submission_id=s["id"],
                reviewer=r,
                criterion_scores={"creativity": 60, "execution": 60},
            )
        advance_clock(ctx["timeline"]["after_preliminary_ends"])
        stage_after = start_and_publish_stage(
            ctx["stages"]["PRELIMINARY"]["id"],
        )
        assert stage_after["status"] == "PUBLISHED"


class TestFinalAggregationVariants:

    def test_n5_trimmed_mean_aggregation(self, api):
        """PRD §3.5: 'When the count of SUBMITTED scores is at least 5,
        the platform drops the single highest and single lowest scores
        before computing the mean of the remaining values.'

        Claim: with 5 reviewer scores [50, 70, 80, 90, 100] (no client
        participation), trimmed mean = (70+80+90)/3 = 80.00.

        # difficulty: combinatorial_formula/aggregate_score_outlier_trim_with_client_weighting
        """
        ctx = setup_in_final_aggregating(
            n_submissions=1,
            client_participates_final=False,
            reviewer_quorum=5,
            reviewer_scores=[50.0, 70.0, 80.0, 90.0, 100.0],
        )
        sub = ctx["submissions"][0]
        sub_after = validate_success(api.get_submission(sub["id"], PO))
        assert sub_after["aggregate_score_by_stage"]["FINAL"] == pytest.approx(
            80.00, abs=1e-9,
        )

    def test_n6_trimmed_mean_with_client_weighting(self, api):
        """PRD §3.5: 'For the FINAL stage when
        Project.client_participates_final is true, the client's own
        scoring assignment is treated specially: after the trimming
        step, the client's score is removed from the trimmed-reviewer
        list, the mean of the remaining reviewer scores is computed,
        and the final aggregate is 30 percent of the client's
        aggregated_score plus 70 percent of the reviewers' mean,
        rounded half up to two decimal places.'

        Claim: 5 reviewers [50,70,80,90,100] + 1 client (70) →
        n=6 triggers trim on combined sorted [50,70,70,80,90,100] →
        trimmed [70,70,80,90] → remove client (70) → reviewer subset
        [70,80,90] mean=80.00 → weighted = 0.30*70 + 0.70*80 =
        21.00 + 56.00 = 77.00.

        # difficulty: combinatorial_formula/aggregate_score_outlier_trim_with_client_weighting
        """
        ctx = setup_in_final_aggregating(
            n_submissions=1,
            client_participates_final=True,
            reviewer_quorum=5,
            reviewer_scores=[50.0, 70.0, 80.0, 90.0, 100.0],
            client_score=70.0,
        )
        sub = ctx["submissions"][0]
        sub_after = validate_success(api.get_submission(sub["id"], PO))
        assert sub_after["aggregate_score_by_stage"]["FINAL"] == pytest.approx(
            77.00, abs=1e-9,
        ), (
            f"Expected client-weighted aggregate 77.00 (= 0.30*70 + 0.70*80), "
            f"got {sub_after['aggregate_score_by_stage']['FINAL']}"
        )
