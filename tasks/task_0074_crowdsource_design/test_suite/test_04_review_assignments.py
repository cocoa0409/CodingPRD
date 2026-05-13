"""Reviewer assignment, qualification, conflict, capacity (PRD §3.4)
and scoring formula rounding-order pin (PRD §3.5).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PO,
    assign_reviewer,
    create_reviewer,
    add_designer_with_submission,
    advance_clock,
    create_review_assignment_payload,
    iso_at,
    make_reviewer_headers,
    setup_on_shelf_project,
    setup_review_assignment_in_submitted,
    submit_scores_payload,
    validate_error,
    validate_success,
)


class TestReviewerQualification:

    def test_reviewer_not_qualified_rejected(self, api):
        """PRD §3.4: 'the reviewer must be qualified for the project —
        that is, the reviewer's categories must include the project's
        category_code, otherwise ERR_REVIEWER_NOT_QUALIFIED.'

        Claim: a reviewer whose categories do not include the project's
        category_code gets ERR_REVIEWER_NOT_QUALIFIED.
        """
        ctx = setup_on_shelf_project()
        designer, sub = add_designer_with_submission(
            ctx["project"]["id"],
            categories=[ctx["category"]["code"]],
        )
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        # A reviewer qualified for a DIFFERENT registered category.
        # PRD §3.4 talks about category mismatch, not FK existence —
        # both categories must be valid catalog entries.
        from test_helpers import create_design_category
        other_cat = create_design_category()
        bad_reviewer = create_reviewer(
            categories=[other_cat["code"]],
            max_concurrent_assignments=20,
        )
        resp = api.create_review_assignment(
            create_review_assignment_payload(
                review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
                submission_id=sub["id"],
                reviewer_id=bad_reviewer["reviewer_id"],
            ),
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_NOT_QUALIFIED.value)


class TestReviewerConflict:

    def test_reviewer_conflict_of_interest_rejected(self, api):
        """PRD §3.4: 'the reviewer must not be in conflict of interest
        with the designer behind the submission. Conflict means the
        designer's Designer.id appears in that reviewer's
        conflict_designer_ids; a violation surfaces
        ERR_REVIEWER_CONFLICT_OF_INTEREST.'

        Claim: assignment for a designer who appears in
        reviewer.conflict_designer_ids returns
        ERR_REVIEWER_CONFLICT_OF_INTEREST.
        """
        ctx = setup_on_shelf_project()
        designer, sub = add_designer_with_submission(
            ctx["project"]["id"],
            categories=[ctx["category"]["code"]],
        )
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        conflict_reviewer = create_reviewer(
            categories=[ctx["category"]["code"]],
            max_concurrent_assignments=20,
            conflict_designer_ids=[designer["id"]],
        )
        resp = api.create_review_assignment(
            create_review_assignment_payload(
                review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
                submission_id=sub["id"],
                reviewer_id=conflict_reviewer["reviewer_id"],
            ),
            PO,
        )
        validate_error(resp,
                       ApiErrorId.ERR_REVIEWER_CONFLICT_OF_INTEREST.value)


class TestReviewerCapacity:

    def test_reviewer_capacity_exceeded_rejected(self, api):
        """PRD §3.4: 'The reviewer also cannot be overcommitted: the
        reviewer's current count of PENDING assignments across all
        stages must not exceed their max_concurrent_assignments cap,
        otherwise ERR_REVIEWER_CAPACITY_EXCEEDED.'

        Claim: a reviewer with max_concurrent_assignments=1 and one
        existing PENDING assignment is rejected on the second create
        with ERR_REVIEWER_CAPACITY_EXCEEDED.
        """
        ctx = setup_on_shelf_project()
        # Two submissions in the same project so the reviewer would have
        # two PENDING assignments.
        d1, s1 = add_designer_with_submission(
            ctx["project"]["id"],
            categories=[ctx["category"]["code"]],
        )
        d2, s2 = add_designer_with_submission(
            ctx["project"]["id"],
            categories=[ctx["category"]["code"]],
        )
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        cap_reviewer = create_reviewer(
            categories=[ctx["category"]["code"]],
            max_concurrent_assignments=1,
        )
        # First assignment ok.
        validate_success(api.create_review_assignment(
            create_review_assignment_payload(
                review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
                submission_id=s1["id"],
                reviewer_id=cap_reviewer["reviewer_id"],
            ),
            PO,
        ), expected_status=201)
        # Second assignment exceeds cap.
        resp = api.create_review_assignment(
            create_review_assignment_payload(
                review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
                submission_id=s2["id"],
                reviewer_id=cap_reviewer["reviewer_id"],
            ),
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_CAPACITY_EXCEEDED.value)


class TestCriterionScoresValidation:

    def test_criterion_scores_missing_key_rejected(self, api):
        """PRD §3.4: 'the submitted keys of criterion_scores must equal
        the keys of the stage's rubric exactly and every score must
        fall within 0 to 100 (otherwise ERR_CRITERION_SCORES_INVALID).'

        Claim: missing a rubric key in criterion_scores returns
        ERR_CRITERION_SCORES_INVALID.
        """
        ctx = setup_on_shelf_project(rubric={"creativity": 50,
                                              "execution": 50})
        designer, sub = add_designer_with_submission(
            ctx["project"]["id"], categories=[ctx["category"]["code"]],
        )
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        reviewer = create_reviewer(
            categories=[ctx["category"]["code"]],
            max_concurrent_assignments=10,
        )
        asg = assign_reviewer(
            review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
            submission_id=sub["id"],
            reviewer_id=reviewer["reviewer_id"],
        )
        resp = api.submit_scores(
            asg["id"],
            submit_scores_payload(criterion_scores={"creativity": 80}),
            make_reviewer_headers(reviewer["reviewer_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CRITERION_SCORES_INVALID.value)

    def test_criterion_scores_out_of_range_rejected(self, api):
        """PRD §3.4: 'every score must fall within 0 to 100 (otherwise
        ERR_CRITERION_SCORES_INVALID).'

        Claim: a score > 100 returns ERR_CRITERION_SCORES_INVALID.
        """
        ctx = setup_on_shelf_project(rubric={"creativity": 50,
                                              "execution": 50})
        designer, sub = add_designer_with_submission(
            ctx["project"]["id"], categories=[ctx["category"]["code"]],
        )
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        reviewer = create_reviewer(
            categories=[ctx["category"]["code"]],
            max_concurrent_assignments=10,
        )
        asg = assign_reviewer(
            review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
            submission_id=sub["id"],
            reviewer_id=reviewer["reviewer_id"],
        )
        resp = api.submit_scores(
            asg["id"],
            submit_scores_payload(criterion_scores={"creativity": 150,
                                                    "execution": 80}),
            make_reviewer_headers(reviewer["reviewer_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CRITERION_SCORES_INVALID.value)


class TestAssignmentAggregatedScore:
    """PRD §3.5: 'The rounding order is strictly pinned: each incoming
    criterion score in criterion_scores is first rounded half up to two
    decimal places (input pre-rounding); each pre-rounded score is then
    multiplied by the corresponding weight from the stage's rubric
    divided by 100; the resulting products are summed at full precision
    (no per-criterion product rounding); and the final sum is rounded
    half up to two decimal places to produce aggregated_score.'"""

    def test_aggregated_score_rounding_order_pinned(self, api):
        """PRD §3.5: 'the resulting products are summed at full
        precision (no per-criterion product rounding); and the final
        sum is rounded half up to two decimal places to produce
        aggregated_score.'

        Claim: with rubric {a:33.33, b:33.33, c:33.34} and scores {1,1,1},
        full-precision sum is 0.3333 + 0.3333 + 0.3334 = 1.0000 ->
        aggregated_score == 1.00. Per-criterion pre-rounding would give
        0.33+0.33+0.33 = 0.99 — divergent.

        # difficulty: combinatorial_formula/assignment_score_rounding_order_pin
        """
        ctx = setup_review_assignment_in_submitted(
            rubric={"creativity": 33.33, "execution": 33.33,
                    "brief_fit": 33.34},
            criterion_scores={"creativity": 1, "execution": 1,
                              "brief_fit": 1},
        )
        asg = ctx["assignment"]
        # The fixture already SUBMITTED the assignment.
        assert asg["status"] == "SUBMITTED"
        assert asg["aggregated_score"] == pytest.approx(1.00, abs=1e-9), (
            f"Expected aggregated_score=1.00 (round-once-at-end), got "
            f"{asg['aggregated_score']}"
        )

    def test_aggregated_score_rounding_order_pinned_observable_divergence(self, api):
        """PRD §3.5: 'the resulting products are summed at full
        precision (no per-criterion product rounding); and the final
        sum is rounded half up to two decimal places to produce
        aggregated_score.'

        Claim: 1.00 != 0.99 confirms the rounding-order pin is observable
        on the SAME rubric+scores inputs.

        # difficulty: combinatorial_formula/assignment_score_rounding_order_pin
        """
        ctx = setup_review_assignment_in_submitted(
            rubric={"creativity": 33.33, "execution": 33.33,
                    "brief_fit": 33.34},
            criterion_scores={"creativity": 1, "execution": 1,
                              "brief_fit": 1},
        )
        asg = ctx["assignment"]
        # The alternative (per-criterion pre-round) would yield 0.99.
        assert asg["aggregated_score"] != pytest.approx(0.99, abs=1e-9), (
            "Per-criterion pre-rounding (0.33+0.33+0.33=0.99) would "
            "violate PRD's pinned 'sum at full precision, then round once' "
            "order"
        )


class TestReviewerAssignmentAnonymity:

    def test_review_assignment_carries_anonymized_alias(self, api):
        """PRD §3.4: 'Every ReviewAssignment is created in PENDING and
        is minted with an anonymized_alias — a server-generated short
        string that the reviewer sees in place of the designer's
        identity until the project is awarded.'

        Claim: a freshly created ReviewAssignment has a non-empty
        anonymized_alias.
        """
        ctx = setup_on_shelf_project()
        designer, sub = add_designer_with_submission(
            ctx["project"]["id"], categories=[ctx["category"]["code"]],
        )
        advance_clock(ctx["timeline"]["after_submission_deadline"])
        reviewer = create_reviewer(
            categories=[ctx["category"]["code"]],
            max_concurrent_assignments=10,
        )
        asg = assign_reviewer(
            review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
            submission_id=sub["id"],
            reviewer_id=reviewer["reviewer_id"],
        )
        assert isinstance(asg.get("anonymized_alias"), str)
        assert len(asg["anonymized_alias"]) > 0
