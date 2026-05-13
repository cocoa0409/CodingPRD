"""Project authoring, prize tiers, review stages, and timeline rules
(PRD §3.2 + §2.6).

Covers: project DRAFT creation, prize-amount/pool checks, timeline
gaps (72h, 168h), rubric weight validation, stage overlap rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_design_category,
    create_client,
    create_prize_tier_payload,
    create_project_payload,
    create_review_stage_payload,
    iso_at,
    make_client_headers,
    setup_stage_overlap_baseline,
    setup_project_ready_for_submit,
    validate_error,
    validate_success,
    PO,
)


# ---------------------------------------------------------------------------
# Project creation — prize amount & pool boundaries
# ---------------------------------------------------------------------------
class TestPrizeAmountValidation:

    def test_prize_pool_below_floor_rejected(self, api):
        """PRD §3.2: 'A request that creates a project with prize_pool_cents
        below 100,000 cents (i.e., below 1,000.00 in major units), or a
        gross_amount_cents below 0 on any tier, is rejected with
        ERR_PRIZE_AMOUNT_INVALID.'

        Claim: prize_pool_cents=99_999 returns ERR_PRIZE_AMOUNT_INVALID.
        """
        cat = create_design_category()
        client = create_client()
        resp = api.create_project(
            create_project_payload(
                client_id=client["id"],
                category_code=cat["code"],
                prize_pool_cents=99_999,
            ),
            make_client_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRIZE_AMOUNT_INVALID.value)

    def test_prize_pool_at_floor_accepted(self, api):
        """PRD §3.2: 'A request that creates a project with
        prize_pool_cents below 100,000 cents (i.e., below 1,000.00 in
        major units) ... is rejected with ERR_PRIZE_AMOUNT_INVALID.'

        Claim: prize_pool_cents=100_000 (exactly the floor) is accepted.
        """
        cat = create_design_category()
        client = create_client()
        resp = api.create_project(
            create_project_payload(
                client_id=client["id"],
                category_code=cat["code"],
                prize_pool_cents=100_000,
            ),
            make_client_headers(client["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["prize_pool_cents"] == 100_000

    def test_prize_tier_negative_gross_rejected(self, api):
        """PRD §3.2: 'A request that creates a project with
        prize_pool_cents below 100,000 cents (i.e., below 1,000.00 in
        major units), or a gross_amount_cents below 0 on any tier, is
        rejected with ERR_PRIZE_AMOUNT_INVALID.'

        Claim: posting a PrizeTier with gross_amount_cents=-1 returns
        ERR_PRIZE_AMOUNT_INVALID.
        """
        cat = create_design_category()
        client = create_client()
        proj = validate_success(api.create_project(
            create_project_payload(
                client_id=client["id"],
                category_code=cat["code"],
                prize_pool_cents=200_000,
            ),
            make_client_headers(client["id"]),
        ), expected_status=201)
        resp = api.create_prize_tier(
            proj["id"],
            create_prize_tier_payload(
                rank=1,
                gross_amount_cents=-1,
                tier_kind="MAIN",
            ),
            make_client_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRIZE_AMOUNT_INVALID.value)


# ---------------------------------------------------------------------------
# Timeline boundary precision tests
# ---------------------------------------------------------------------------
class TestProjectTimeline:

    def test_submission_deadline_72h_gap_too_tight(self, api):
        """PRD §3.2: 'submission_deadline must be no earlier than 72
        hours after opens_at ... A request that fails either bound is
        rejected with ERR_TIMELINE_TOO_TIGHT.'

        Claim: 48-hour gap (under the 72-hour floor) returns
        ERR_TIMELINE_TOO_TIGHT.
        """
        cat = create_design_category()
        client = create_client()
        resp = api.create_project(
            create_project_payload(
                client_id=client["id"],
                category_code=cat["code"],
                opens_at=iso_at(2026, 6, 1, 0),
                submission_deadline=iso_at(2026, 6, 3, 0),  # 48h gap
                final_decision_deadline=iso_at(2026, 6, 15, 0),
            ),
            make_client_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TIMELINE_TOO_TIGHT.value)

    def test_submission_deadline_72h_gap_exact_accepted(self, api):
        """PRD §3.2: 'submission_deadline must be no earlier than 72
        hours after opens_at.'

        Claim: submission_deadline = opens_at + 72h exactly is accepted.

        # difficulty: resource_temporal_overlap/project_min_gap_intervals_aggregate
        """
        cat = create_design_category()
        client = create_client()
        resp = api.create_project(
            create_project_payload(
                client_id=client["id"],
                category_code=cat["code"],
                opens_at=iso_at(2026, 6, 1, 0),
                submission_deadline=iso_at(2026, 6, 4, 0),  # exactly 72h
                final_decision_deadline=iso_at(2026, 6, 15, 0),
            ),
            make_client_headers(client["id"]),
        )
        validate_success(resp, expected_status=201)

    def test_final_decision_168h_gap_too_tight(self, api):
        """PRD §3.2: 'final_decision_deadline must be no earlier than
        168 hours (seven full days) after submission_deadline. A
        request that fails either bound is rejected with
        ERR_TIMELINE_TOO_TIGHT.'

        Claim: gap of 24h (under 168h floor) returns
        ERR_TIMELINE_TOO_TIGHT.

        # difficulty: resource_temporal_overlap/project_min_gap_intervals_aggregate
        """
        cat = create_design_category()
        client = create_client()
        resp = api.create_project(
            create_project_payload(
                client_id=client["id"],
                category_code=cat["code"],
                opens_at=iso_at(2026, 6, 1, 0),
                submission_deadline=iso_at(2026, 6, 5, 0),
                final_decision_deadline=iso_at(2026, 6, 6, 0),  # 24h after SD
            ),
            make_client_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TIMELINE_TOO_TIGHT.value)


# ---------------------------------------------------------------------------
# Rubric weight validation
# ---------------------------------------------------------------------------
class TestRubricWeights:

    def test_rubric_weights_not_sum_100_rejected(self, api):
        """PRD §3.2: 'The rubric must contain between 1 and 8 criteria
        whose weights sum to exactly 100; any departure is rejected
        with ERR_RUBRIC_WEIGHTS_INVALID.'

        Claim: weights summing to 80 (not 100) return
        ERR_RUBRIC_WEIGHTS_INVALID.
        """
        ctx = setup_stage_overlap_baseline()
        resp = api.create_review_stage(
            ctx["project"]["id"],
            create_review_stage_payload(
                rubric={"creativity": 40, "execution": 40},
                starts_at=iso_at(2026, 6, 10),
                ends_at=iso_at(2026, 6, 12),
            ),
            make_client_headers(ctx["client"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RUBRIC_WEIGHTS_INVALID.value)

    def test_rubric_weights_exactly_100_accepted(self, api):
        """PRD §3.2: 'The rubric must contain between 1 and 8 criteria
        whose weights sum to exactly 100.'

        Claim: weights summing to exactly 100 are accepted.
        """
        ctx = setup_stage_overlap_baseline()
        resp = api.create_review_stage(
            ctx["project"]["id"],
            create_review_stage_payload(
                stage_kind="PRELIMINARY",
                rubric={"a": 33.33, "b": 33.33, "c": 33.34},
                starts_at=iso_at(2026, 6, 10),
                ends_at=iso_at(2026, 6, 12),
            ),
            make_client_headers(ctx["client"]["id"]),
        )
        validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Stage overlap rule (half-open intervals)
# ---------------------------------------------------------------------------
class TestStageOverlap:

    def test_adjacent_stage_boundaries_accepted(self, api):
        """PRD §3.2: 'The three stages on a project must form a
        strictly ordered, non-overlapping sequence: the preliminary
        stage's ends_at must be no later than the semifinal stage's
        starts_at, and the semifinal stage's ends_at must be no later
        than the final stage's starts_at.'

        Claim: PRELIMINARY.ends_at == SEMIFINAL.starts_at (adjacency)
        is permitted because the rule uses 'no later than' (<=).

        # difficulty: resource_temporal_overlap/stage_intervals_half_open_no_overlap
        """
        ctx = setup_stage_overlap_baseline()
        client = ctx["client"]
        proj = ctx["project"]
        # PRELIMINARY: T1..T2
        r1 = api.create_review_stage(
            proj["id"],
            create_review_stage_payload(
                stage_kind="PRELIMINARY",
                starts_at=iso_at(2026, 6, 10),
                ends_at=iso_at(2026, 6, 12),
            ),
            make_client_headers(client["id"]),
        )
        validate_success(r1, expected_status=201)
        # SEMIFINAL: T2..T3 (boundary adjacency)
        r2 = api.create_review_stage(
            proj["id"],
            create_review_stage_payload(
                stage_kind="SEMIFINAL",
                starts_at=iso_at(2026, 6, 12),
                ends_at=iso_at(2026, 6, 14),
            ),
            make_client_headers(client["id"]),
        )
        validate_success(r2, expected_status=201)

    def test_positive_overlap_with_existing_stage_rejected(self, api):
        """PRD §3.2: 'A violation surfaces ERR_STAGE_OVERLAP.'

        Claim: positive overlap between two stages returns
        ERR_STAGE_OVERLAP.

        # difficulty: resource_temporal_overlap/stage_intervals_half_open_no_overlap
        """
        ctx = setup_stage_overlap_baseline()
        client = ctx["client"]
        proj = ctx["project"]
        # PRELIMINARY T1..T2.
        validate_success(api.create_review_stage(
            proj["id"],
            create_review_stage_payload(
                stage_kind="PRELIMINARY",
                starts_at=iso_at(2026, 6, 10),
                ends_at=iso_at(2026, 6, 12),
            ),
            make_client_headers(client["id"]),
        ), expected_status=201)
        # SEMIFINAL T2..T3.
        validate_success(api.create_review_stage(
            proj["id"],
            create_review_stage_payload(
                stage_kind="SEMIFINAL",
                starts_at=iso_at(2026, 6, 12),
                ends_at=iso_at(2026, 6, 14),
            ),
            make_client_headers(client["id"]),
        ), expected_status=201)
        # FINAL T2-1h..T3+1h — positive overlap with SEMIFINAL.
        resp = api.create_review_stage(
            proj["id"],
            create_review_stage_payload(
                stage_kind="FINAL",
                starts_at=iso_at(2026, 6, 11, 23),  # 1h before SEMI starts
                ends_at=iso_at(2026, 6, 15),
            ),
            make_client_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STAGE_OVERLAP.value)


# ---------------------------------------------------------------------------
# submit-for-review preconditions
# ---------------------------------------------------------------------------
class TestSubmitForReview:

    def test_prize_pool_sum_mismatch_rejected(self, api):
        """PRD §3.2: 'Five preconditions are enforced together: the sum
        of PrizeTier.gross_amount_cents across the project's tiers must
        equal prize_pool_cents exactly (otherwise
        ERR_PRIZE_POOL_MISMATCH).'

        Claim: when tier gross totals do not equal prize_pool_cents,
        submit-for-review returns ERR_PRIZE_POOL_MISMATCH.
        """
        ctx = setup_project_ready_for_submit(
            prize_pool_cents=1_000_000,
            tiers=[{"rank": 1, "gross_amount_cents": 500_000,
                    "tier_kind": "MAIN"}],
        )
        resp = api.submit_project_for_review(
            ctx["project"]["id"],
            make_client_headers(ctx["client"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRIZE_POOL_MISMATCH.value)

    def test_submit_for_review_success(self, api):
        """PRD §3.2: 'When the client is ready, they submit the project
        for platform review, advancing Project.status from DRAFT to
        UNDER_PLATFORM_REVIEW.'

        Claim: a valid configuration moves the project to
        UNDER_PLATFORM_REVIEW.
        """
        ctx = setup_project_ready_for_submit()
        resp = api.submit_project_for_review(
            ctx["project"]["id"],
            make_client_headers(ctx["client"]["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "UNDER_PLATFORM_REVIEW", (
            f"Expected UNDER_PLATFORM_REVIEW, got {data['status']!r}"
        )
