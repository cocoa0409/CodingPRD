"""
Composite scoring, the two score variants and the bounded second deliberation round.
"""

from test_helpers import (
    PROGRAM_OFFICER,
    REVIEW_SCORES_600,
    REVIEW_SCORES_700,
    REVIEW_SCORES_800,
    REVIEW_SCORES_800_FLAT,
    REVIEW_SCORES_860,
    api_client,
    assert_application_scores,
    assert_score,
    cyclemain_panel_chartered,
    cyclemain_reviews_submitted,
    cyclemain_round_closed,
    list_reviews_of,
    read_application,
    read_panel,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import _draft_and_submit_review


class TestCompositeScoreVariants:
    """The provisional mean and the trimmed final mean on one review set."""

    def test_provisional_mean_is_published_while_the_final_variant_stays_null(self):
        """
        Five counted reviews scoring 8.00, 6.60, 7.30, 6.00 and 8.50 publish a
        provisional composite of 7.28 while the round is still open, and nothing has
        yet been written into the field the slate ranks on.

        PRD: "Two composite variants are computed over that same set and stored in
        different fields, so their divergence is observable in a single response."

        Design: Difficulty/dual_variant_calc/composite_score_provisional_mean_vs_final_trimmed_mean
        """
        ctx = cyclemain_reviews_submitted()

        application = read_application(ctx.app1)
        assert application["status"] == "UNDER_REVIEW", (
            f"application should still be UNDER_REVIEW, got {application['status']}"
        )
        assert application["valid_review_count"] == 5, (
            "all five submitted reviews of the open round should be counted, got "
            f"{application['valid_review_count']}"
        )
        assert_score(
            application["provisional_composite_score"],
            7.28,
            "application.provisional_composite_score",
        )
        assert application["final_composite_score"] is None, (
            "final_composite_score is written once per round at close, so it should "
            f"still be null, got {application['final_composite_score']}"
        )

    def test_closing_the_round_writes_the_trimmed_final_variant_beside_the_provisional(self):
        """
        Closing the round trims the highest 8.50 and the lowest 6.00 and averages the
        surviving 8.00, 6.60 and 7.30 to 7.30, leaving the untrimmed provisional 7.28
        in place beside it and stamping the spread over the whole counted set.

        PRD: "The **final** variant is written once per round when the round closes, is
        exposed as `final_composite_score`, and is the figure the slate ranks on."

        Design: Difficulty/dual_variant_calc/composite_score_provisional_mean_vs_final_trimmed_mean
        """
        ctx = cyclemain_round_closed()

        application = read_application(ctx.app1)
        assert application["status"] == "SCORED", (
            f"application should be SCORED after the round closes, got {application['status']}"
        )
        assert_application_scores(
            application,
            valid_review_count=5,
            provisional_composite_score=7.28,
            final_composite_score=7.30,
            score_spread=2.50,
        )
        assert application["review_round_number"] == 1, (
            "review_round_number should record the closing round 1, got "
            f"{application['review_round_number']}"
        )


class TestSpreadAtTheReopenThreshold:
    """A spread sitting exactly on 2.50 must not reopen the round."""

    def test_spread_of_exactly_two_point_five_zero_settles_the_panel(self):
        """
        A counted set of 8.00, 6.60, 7.30, 6.00 and 8.50 spreads exactly 2.50, which
        leaves `reopen_required` false, settles the panel into deliberation and moves
        the application on to SCORED.

        PRD: "A spread of exactly 2.50 does not reopen a round; a spread of 4.10 does."

        Design: Difficulty/boundary_precision_check/score_spread_exactly_at_reopen_threshold_does_not_reopen
        """
        ctx = cyclemain_round_closed()

        panel = read_panel(ctx.pan)
        assert panel["status"] == "DELIBERATING", (
            f"panel should be DELIBERATING, got {panel['status']}"
        )
        assert panel["reopen_required"] is False, (
            "a spread of exactly 2.50 must not set reopen_required, got "
            f"{panel['reopen_required']}"
        )
        assert read_application(ctx.app1)["status"] == "SCORED", (
            "the application should move UNDER_REVIEW -> SCORED when no reopen is required"
        )

    def test_the_settled_round_keeps_both_variants_and_its_round_number(self):
        """
        The settled round leaves the trimmed final composite at 7.30 beside the
        untrimmed provisional 7.28, with the spread measured over the whole counted set
        rather than over the trimmed remainder.

        PRD: "`score_spread` is always measured over the whole counted set and never
        over the trimmed remainder: it is the maximal `weighted_score` less the minimal
        `weighted_score` among the counted reviews, rounded half up to two decimals."

        Design: Difficulty/boundary_precision_check/score_spread_exactly_at_reopen_threshold_does_not_reopen
        """
        ctx = cyclemain_round_closed()

        application = read_application(ctx.app1)
        assert_application_scores(
            application,
            valid_review_count=5,
            provisional_composite_score=7.28,
            final_composite_score=7.30,
            score_spread=2.50,
        )
        assert application["review_round_number"] == 1, (
            f"review_round_number should be 1, got {application['review_round_number']}"
        )


class TestBoundedSecondRound:
    """DELIBERATING loops back to SCORING once, and only once."""

    def test_a_spread_above_the_threshold_flags_the_panel_for_another_round(self):
        """
        A fifth review of 8.60 lifts the spread to 2.60, so closing the round flags the
        panel for another pass and holds the application in UNDER_REVIEW instead of
        settling it.

        PRD: "`reopen_required` is then set to true when at least one assigned
        application's `score_spread` is strictly greater than 2.50 **and**
        `round_number` is still below the cycle's `max_review_rounds`; otherwise it is
        set to false and every assigned `UNDER_REVIEW` application moves
        `UNDER_REVIEW → SCORED`."

        Design: Difficulty/non_linear_state_machine/panel_loops_deliberating_back_to_scoring_for_a_bounded_second_round
        """
        ctx = cyclemain_round_closed(fifth_scores=REVIEW_SCORES_860)

        panel = read_panel(ctx.pan)
        assert panel["status"] == "DELIBERATING", (
            f"panel should be DELIBERATING, got {panel['status']}"
        )
        assert panel["round_number"] == 1, (
            f"panel.round_number should still be 1, got {panel['round_number']}"
        )
        assert panel["reopen_required"] is True, (
            "a spread of 2.60 above the 2.50 threshold must set reopen_required"
        )

        application = read_application(ctx.app1)
        assert application["status"] == "UNDER_REVIEW", (
            "an application whose panel must run again stays UNDER_REVIEW, got "
            f"{application['status']}"
        )
        assert_application_scores(
            application,
            valid_review_count=5,
            provisional_composite_score=7.30,
            final_composite_score=7.30,
            score_spread=2.60,
        )

    def test_a_flagged_panel_blocks_the_cycle_from_reaching_board_review(self):
        """
        While a panel of the cycle still carries `reopen_required`, the cycle cannot be
        advanced out of panel review.

        PRD: "`PANEL_REVIEW → BOARD_REVIEW` requires every panel of the cycle to be in
        `DELIBERATING`, `SLATE_SUBMITTED` or `DISSOLVED`, failing which the request is
        rejected with `ERR_PANEL_STATE_INVALID`, and requires that no panel still have
        `reopen_required` set, failing which it is rejected with
        `ERR_SCORE_SPREAD_REQUIRES_ANOTHER_ROUND`; the posture is recomputed."

        Design: Difficulty/non_linear_state_machine/panel_loops_deliberating_back_to_scoring_for_a_bounded_second_round
        """
        ctx = cyclemain_round_closed(fifth_scores=REVIEW_SCORES_860)

        response = api_client.set_cycle_status(ctx.cyc, "BOARD_REVIEW", PROGRAM_OFFICER)
        validate_error(response, "ERR_SCORE_SPREAD_REQUIRES_ANOTHER_ROUND")

    def test_reopening_supersedes_the_first_round_and_clears_the_derived_scores(self):
        """
        Reopening lifts the panel to round 2, clears the reopen flag, supersedes every
        first-round review and leaves the application with no counted review and null
        composites.

        PRD: "Reopening increments `round_number` by one, resets `reopen_required` to
        false, and supersedes the past: every review on the panel's assigned
        applications in `SUBMITTED` or `INVALIDATED` whose `round_number` is below the
        new round becomes `SUPERSEDED`, after which each assigned application's
        `valid_review_count`, `provisional_composite_score` and `score_spread` are
        recomputed and read `null` where no counted review remains."

        Design: Difficulty/non_linear_state_machine/panel_loops_deliberating_back_to_scoring_for_a_bounded_second_round
        """
        ctx = cyclemain_round_closed(fifth_scores=REVIEW_SCORES_860)

        panel = validate_success(api_client.open_round(ctx.pan, PROGRAM_OFFICER))
        assert panel["status"] == "SCORING", (
            f"panel should return DELIBERATING -> SCORING, got {panel['status']}"
        )
        assert panel["round_number"] == 2, (
            f"panel.round_number should be 2, got {panel['round_number']}"
        )
        assert panel["reopen_required"] is False, (
            "reopening resets reopen_required to false"
        )

        statuses = [row["status"] for row in list_reviews_of(ctx.app1)]
        assert statuses == ["SUPERSEDED"] * 5, (
            f"all five round-1 reviews should be SUPERSEDED, got {statuses}"
        )

        application = read_application(ctx.app1)
        assert_application_scores(
            application,
            valid_review_count=0,
            provisional_composite_score=None,
            final_composite_score=None,
            score_spread=None,
        )

    def test_the_second_round_scores_afresh_and_the_third_round_is_refused(self):
        """
        Round 2 scores afresh under the new round number, closes with a final composite
        of 7.00 and a spread of 2.00, and the panel — having reached the cycle's ceiling
        of two rounds — refuses a third opening.

        PRD: "That requires `reopen_required` to be true and `round_number` to be
        strictly below `max_review_rounds`, either failure reported as
        `ERR_PANEL_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/panel_loops_deliberating_back_to_scoring_for_a_bounded_second_round
        """
        ctx = cyclemain_round_closed(fifth_scores=REVIEW_SCORES_860)
        validate_success(api_client.open_round(ctx.pan, PROGRAM_OFFICER))

        for panelist_id, scores in (
            (ctx.pl1, REVIEW_SCORES_800_FLAT),
            (ctx.pl2, REVIEW_SCORES_700),
            (ctx.pl3, REVIEW_SCORES_600),
        ):
            _draft_and_submit_review(ctx.app1, panelist_id, scores, "Second-round read.")

        assert_score(
            read_application(ctx.app1)["provisional_composite_score"],
            7.00,
            "application.provisional_composite_score after three round-2 reviews",
        )

        validate_success(api_client.close_round(ctx.pan, PROGRAM_OFFICER))
        application = read_application(ctx.app1)
        assert application["status"] == "SCORED", (
            f"the second round should settle the application, got {application['status']}"
        )
        assert_application_scores(
            application,
            valid_review_count=3,
            provisional_composite_score=7.00,
            final_composite_score=7.00,
            score_spread=2.00,
        )
        assert application["review_round_number"] == 2, (
            f"review_round_number should be 2, got {application['review_round_number']}"
        )

        validate_error(
            api_client.open_round(ctx.pan, PROGRAM_OFFICER), "ERR_PANEL_STATE_INVALID"
        )


class TestReviewSubmissionGates:
    """A review's own legality is not enough; its panel and its round must agree."""

    def test_a_review_drafted_before_the_round_opens_cannot_be_submitted(self):
        """
        A chartered panel that has not yet opened a round stamps its drafts with round 0
        and refuses their submission on panel state alone.

        PRD: "The panel must be in `SCORING` — a review that is perfectly legal in
        isolation is refused with `ERR_PANEL_STATE_INVALID` when its panel has not yet
        opened a round or has already closed one."

        Design: Difficulty/cross_entity_state_dependency/review_submission_gated_on_panel_scoring_and_matching_round
        """
        ctx = cyclemain_panel_chartered()

        draft = validate_success(
            api_client.create_review(
                {
                    "application_id": ctx.app1,
                    "panelist_id": ctx.pl1,
                    "artistic_excellence": 9,
                    "work_sample_quality": 8,
                    "career_impact": 7,
                    "public_value": 6,
                    "comments": "Drafted before the round opened.",
                },
                ctx.pl1_headers,
            ),
            expected_status=201,
        )
        assert draft["round_number"] == 0, (
            "a draft is stamped from the panel's current round_number, got "
            f"{draft['round_number']}"
        )

        validate_error(
            api_client.submit_review(draft["id"], ctx.pl1_headers),
            "ERR_PANEL_STATE_INVALID",
        )
        assert read_application(ctx.app1)["valid_review_count"] == 0, (
            "a refused submission must not be counted"
        )

    def test_a_round_zero_draft_stays_unsubmittable_once_round_one_opens(self):
        """
        Opening round 1 does not rescue the round-0 draft: its own round number no
        longer matches the panel's, so it is refused and left in DRAFT, while a review
        drafted under round 1 submits and lands on all three rows.

        PRD: "And the review's own `round_number` must equal the panel's current
        `round_number`, otherwise `ERR_REVIEW_STATE_INVALID` — the same code a second
        submission attempt receives."

        Design: Difficulty/cross_entity_state_dependency/review_submission_gated_on_panel_scoring_and_matching_round
        """
        ctx = cyclemain_panel_chartered()
        stale = validate_success(
            api_client.create_review(
                {
                    "application_id": ctx.app1,
                    "panelist_id": ctx.pl1,
                    "artistic_excellence": 9,
                    "work_sample_quality": 8,
                    "career_impact": 7,
                    "public_value": 6,
                    "comments": "Drafted before the round opened.",
                },
                ctx.pl1_headers,
            ),
            expected_status=201,
        )["id"]

        validate_success(api_client.open_round(ctx.pan, PROGRAM_OFFICER))
        validate_error(
            api_client.submit_review(stale, ctx.pl1_headers), "ERR_REVIEW_STATE_INVALID"
        )

        stale_row = validate_success(api_client.get_review(stale, PROGRAM_OFFICER))
        assert stale_row["status"] == "DRAFT", (
            f"the refused review should stay DRAFT, got {stale_row['status']}"
        )
        assert stale_row["submitted_at"] is None, "submitted_at must stay null"
        assert stale_row["weighted_score"] is None, "weighted_score must stay null"

        _draft_and_submit_review(
            ctx.app1, ctx.pl1, REVIEW_SCORES_800, "Assured voice, uneven middle section."
        )
        application = read_application(ctx.app1)
        assert application["valid_review_count"] == 1, (
            f"the round-1 review should count, got {application['valid_review_count']}"
        )
        assert_score(
            application["provisional_composite_score"],
            8.00,
            "application.provisional_composite_score",
        )
        panelist = validate_success(api_client.get_panelist(ctx.pl1, PROGRAM_OFFICER))
        assert panelist["review_submitted_count"] == 1, (
            "only the accepted submission increments review_submitted_count, got "
            f"{panelist['review_submitted_count']}"
        )
