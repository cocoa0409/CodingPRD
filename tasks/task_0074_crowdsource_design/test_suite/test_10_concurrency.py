"""Concurrency and idempotency tests (PRD §2.5, §3.4, §3.8, §3.9).

Race tests are limited to outcomes the PRD explicitly pins:
- POST /review-assignments with duplicate (stage, submission, reviewer)
  guarantees ERR_REVIEWER_ALREADY_ASSIGNED for the loser.
- POST /prize-payments/{id}/dispatch with the same idempotency_key
  guarantees ERR_DUPLICATE_IDEMPOTENCY_KEY for the loser.
- Optimistic concurrency: stale version on PATCH/state-action returns
  ERR_VERSION_CONFLICT.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PO,
    advance_clock,
    add_designer_with_submission,
    assert_exactly_one_succeeds,
    create_review_assignment_payload,
    create_reviewer,
    dispatch_payment_payload,
    iso_at,
    make_designer_headers,
    patch_submission_payload,
    run_race,
    setup_on_shelf_project,
    setup_registered_copyright,
    unique_idempotency_key,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestReviewerAlreadyAssigned:

    def test_duplicate_reviewer_assignment_rejected(self, api):
        """PRD §3.4: 'When two assignments race that would place the
        same reviewer on the same submission within the same stage,
        exactly one wins on the uniqueness constraint over
        (review_stage_id, submission_id, reviewer_id), and the loser
        receives ERR_REVIEWER_ALREADY_ASSIGNED.'

        Claim: sequential duplicate POST /review-assignments returns
        ERR_REVIEWER_ALREADY_ASSIGNED for the second call.
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
        # First assignment OK.
        validate_success(api.create_review_assignment(
            create_review_assignment_payload(
                review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
                submission_id=sub["id"],
                reviewer_id=reviewer["reviewer_id"],
            ),
            PO,
        ), expected_status=201)
        # Duplicate rejected.
        resp = api.create_review_assignment(
            create_review_assignment_payload(
                review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
                submission_id=sub["id"],
                reviewer_id=reviewer["reviewer_id"],
            ),
            PO,
        )
        validate_error(resp,
                       ApiErrorId.ERR_REVIEWER_ALREADY_ASSIGNED.value)


class TestIdempotencyKeyOnDispatch:
    # DELETED: test_duplicate_idempotency_key_rejected
    # Reason: PRD §3.9 says "must be unique across the pair
    # (project_id, prize_tier_id); if a payment with the same key is
    # already PAYING or PAID, the duplicate is rejected". The PRD
    # rejection is gated on the same KEY being PAYING/PAID at the
    # moment of the second dispatch. Since each (project, tier) has
    # exactly one auto-created PrizePayment row, exercising this
    # rejection from the API requires a second dispatch attempt on
    # the same row while it is still PAYING or PAID — but that is
    # blocked first by ERR_INVALID_STATE (PRD §2.9 puts state-check
    # priority 5 ahead of business rules), making
    # ERR_DUPLICATE_IDEMPOTENCY_KEY unreachable under any
    # PRD-faithful setup. The previously-failed-then-retried path
    # also frees the key (per PRD's "PAYING/PAID" qualifier), so the
    # test's expected outcome is not uniquely derivable from PRD.
    # Silence category: STEP-1b unreachable-under-PRD-precedence
    # Scaffold rule driver: concurrency_idempotency_dispatch_unique_key
    pass


class TestOptimisticConcurrency:

    def test_stale_version_on_patch_rejected(self, api):
        """PRD §2.5: 'When version is supplied, the server compares it
        against the current value of the targeted entity's version and
        rejects a mismatch with ERR_VERSION_CONFLICT. ... The check
        uses strict equality on the integer.'

        Claim: PATCH /submissions/{id} with a stale version returns
        ERR_VERSION_CONFLICT.
        """
        ctx = setup_on_shelf_project()
        designer, sub = add_designer_with_submission(
            ctx["project"]["id"], categories=[ctx["category"]["code"]],
        )
        # First PATCH advances version to 2 (or beyond).
        validate_success(api.patch_submission(
            sub["id"],
            patch_submission_payload(title="first edit"),
            make_designer_headers(designer["id"]),
        ))
        # Second PATCH supplying the stale version=1 must fail.
        resp = api.patch_submission(
            sub["id"],
            patch_submission_payload(title="second edit", version=1),
            make_designer_headers(designer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)


class TestConcurrentReviewerAssignment:

    def test_race_only_one_assignment_succeeds(self, api):
        """PRD §3.4: 'When two assignments race that would place the
        same reviewer on the same submission within the same stage,
        exactly one wins on the uniqueness constraint over
        (review_stage_id, submission_id, reviewer_id), and the loser
        receives ERR_REVIEWER_ALREADY_ASSIGNED.'

        Claim: in a parallel race, exactly one assignment succeeds.
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

        def go():
            return api.create_review_assignment(
                create_review_assignment_payload(
                    review_stage_id=ctx["stages"]["PRELIMINARY"]["id"],
                    submission_id=sub["id"],
                    reviewer_id=reviewer["reviewer_id"],
                ),
                PO,
            )

        r1, r2 = run_race(go, go)
        assert_exactly_one_succeeds(r1, r2)
