"""
The public review calendar and the two conserved quantities: a review's comment
disposition ledger, which a reopening must restore exactly, and a ballot's seat
ledger, which a withdrawal must restore exactly.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestZeroCommentReviewCloses:
    """No comments means fully disposed, not zero percent disposed."""

    def test_zero_comment_close_reports_full_completeness_and_terminates(self, api):
        """
        it moves from `CLOSED` straight to the terminal `DISPOSITION_APPROVED` inside
        that same close request, skipping `DISPOSITION_DRAFTED` entirely, with
        `disposition_completeness_pct` at 100.0, `disposition_approved_at` set from
        the logical clock, and `disposition_approved_by_participant_id` left null
        because nobody approved it.

        Design: Difficulty/boundary_precision_check/zero_comment_public_review_closes_at_full_disposition_completeness_not_zero
        """
        scenario = fx.announced_zero_comment_public_review(api)
        assert scenario.get_public_review()["status"] == "OPEN", (
            "the window has elapsed but the close has not been performed yet"
        )

        scenario.close_public_review()

        review = scenario.get_public_review()
        a.assert_comment_ledger(
            review,
            comment_count=0,
            disposed_count=0,
            unresolved_count=0,
            completeness_pct=100.0,
        )
        assert review["status"] == "DISPOSITION_APPROVED", (
            f"status expected DISPOSITION_APPROVED, got {review['status']}"
        )
        a.assert_same_instant(review["closed_at"], "2026-09-15T00:00:00Z")
        a.assert_same_instant(review["disposition_approved_at"], "2026-09-15T00:00:00Z")
        assert review["disposition_approved_by_participant_id"] is None, (
            "nobody approved it, so the approver stays null; got "
            f"{review['disposition_approved_by_participant_id']}"
        )
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_CLOSED", (
            "the parent draft moves out of public review on the close"
        )

    def test_approving_an_already_approved_disposition_is_refused(self, api):
        """
        Either the secretariat or a committee chair may approve, the review must be in
        `DISPOSITION_DRAFTED` (else `ERR_INVALID_PUBLIC_REVIEW_STATE`), its
        `disposition_completeness_pct` must be exactly 100.0 (else
        `ERR_DISPOSITION_INCOMPLETE`), and the caller's identifier must **differ** from
        the `chair_participant_id` of the committee sponsoring the reviewed draft's
        work item.

        Design: Difficulty/boundary_precision_check/zero_comment_public_review_closes_at_full_disposition_completeness_not_zero
        """
        scenario = fx.announced_zero_comment_public_review(api)
        scenario.close_public_review()
        before = scenario.get_public_review()

        response = api.approve_disposition(scenario.public_review_id, scenario.staff)
        validate_error(response, "ERR_INVALID_PUBLIC_REVIEW_STATE", 409)

        after = scenario.get_public_review()
        assert after["status"] == "DISPOSITION_APPROVED", (
            "the terminal status is unmoved by the refused approval"
        )
        a.assert_version_unchanged(before, after)
        assert after["disposition_approved_by_participant_id"] is None, (
            "the refused approval recorded no approver"
        )


class TestReviewCalendarBuffer:
    """Every recorded review widens by fifteen days on both sides."""

    def test_window_starting_on_the_buffered_edge_is_refused(self, api):
        """
        Concretely, an existing review ending 2026-09-14 pushes its buffered edge out
        to 2026-09-29, so a candidate beginning 2026-09-29 collides while one
        beginning 2026-09-30 does not.

        Design: Difficulty/resource_temporal_overlap/work_item_public_review_buffer_rejects_a_window_starting_on_the_buffered_edge
        """
        scenario = fx.revision_two_after_closed_public_review(api)
        revision_two_id = scenario.draft_ids[1]
        before = scenario.get_draft(revision_two_id)
        assert before["status"] == "PUBLIC_REVIEW_READY", (
            f"revision two is ready for its own review, got {before['status']}"
        )

        response = api.create_public_review(
            f.public_review_payload(
                revision_two_id,
                before["version"],
                start_date="2026-09-29",
                end_date="2026-11-12",
            ),
            scenario.staff,
        )
        validate_error(response, "ERR_REVIEW_WINDOW_BUFFER_CONFLICT", 409)

        after = scenario.get_draft(revision_two_id)
        assert after["status"] == "PUBLIC_REVIEW_READY", (
            "the refused announcement left the draft where it was"
        )
        a.assert_version_unchanged(before, after)
        _, meta = validate_paginated(api.list_public_reviews(scenario.staff))
        a.assert_total_count(meta, 1)

    def test_window_starting_one_day_past_the_buffered_edge_is_accepted(self, api):
        """
        Each occupant is widened by 15 days on both sides before collision is tested.

        Design: Difficulty/resource_temporal_overlap/work_item_public_review_buffer_rejects_a_window_starting_on_the_buffered_edge
        """
        scenario = fx.revision_two_after_closed_public_review(api)
        revision_two_id = scenario.draft_ids[1]

        review = scenario.announce_public_review(
            draft_id=revision_two_id,
            start_date="2026-09-30",
            end_date="2026-11-13",
        )
        assert review["status"] == "SCHEDULED", (
            "the window has not started yet at the current clock, got "
            f"{review['status']}"
        )
        assert a.inclusive_day_span("2026-09-30", "2026-11-13") == 45, (
            "the accepted window is the same 45-day length as the refused one"
        )
        a.assert_comment_ledger(
            review,
            comment_count=0,
            disposed_count=0,
            unresolved_count=0,
            completeness_pct=100.0,
        )
        assert scenario.get_draft(revision_two_id)["status"] == "PUBLIC_REVIEW", (
            "the announcement carries revision two into public review"
        )
        _, meta = validate_paginated(api.list_public_reviews(scenario.staff))
        a.assert_total_count(meta, 2)


class TestCommentLedgerIsRestoredByAReopening:
    """A disposition and its reopening leave no counter drift."""

    def test_disposing_the_only_comment_bubbles_the_review_up(self, api):
        """
        when the recomputed `unresolved_comment_count` reaches 0 on a review that has
        at least one comment, the review bubbles up from `CLOSED` to
        `DISPOSITION_DRAFTED` with `disposition_completeness_pct` at 100.0

        Design: Difficulty/compensating_invariant/reopening_a_disposed_public_review_comment_restores_the_ledger_exactly
        """
        scenario = fx.public_review_with_one_comment(api)
        a.assert_comment_ledger(
            scenario.get_public_review(),
            comment_count=1,
            disposed_count=0,
            unresolved_count=1,
            completeness_pct=0.0,
        )

        scenario.dispose_comment(
            scenario.comment_id,
            disposition="ACCEPTED",
            disposition_rationale="The fatigue annex reference will be added",
        )

        review = scenario.get_public_review()
        a.assert_comment_ledger(
            review,
            comment_count=1,
            disposed_count=1,
            unresolved_count=0,
            completeness_pct=100.0,
        )
        assert review["status"] == "DISPOSITION_DRAFTED", (
            f"status expected DISPOSITION_DRAFTED, got {review['status']}"
        )
        assert scenario.get_comment(scenario.comment_id)["status"] == "ACCEPTED", (
            "the comment carries the disposition"
        )
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_CLOSED", (
            "dispositioning never moves the draft"
        )

    def test_reopening_the_comment_restores_every_counter(self, api):
        """
        `REOPENED` is the exact compensation for all three. It returns a comment in
        `ACCEPTED`, `ACCEPTED_WITH_MODIFICATION` or `REJECTED` back to `OPEN`, clears
        its `disposition_rationale` to null, decrements the review's `disposed_count`,
        increments its `unresolved_comment_count`, recomputes
        `disposition_completeness_pct`, and reverses the earlier bubble-up by moving
        the review from `DISPOSITION_DRAFTED` back to `CLOSED` if it had already
        bubbled.

        Design: Difficulty/compensating_invariant/reopening_a_disposed_public_review_comment_restores_the_ledger_exactly
        """
        scenario = fx.public_review_with_one_comment(api)
        scenario.dispose_comment(
            scenario.comment_id,
            disposition="ACCEPTED",
            disposition_rationale="The fatigue annex reference will be added",
        )

        scenario.dispose_comment(
            scenario.comment_id, disposition="REOPENED", disposition_rationale=None
        )

        review = scenario.get_public_review()
        a.assert_comment_ledger(
            review,
            comment_count=1,
            disposed_count=0,
            unresolved_count=1,
            completeness_pct=0.0,
        )
        assert review["status"] == "CLOSED", (
            f"the review falls back to CLOSED, got {review['status']}"
        )
        assert review["disposition_approved_by_participant_id"] is None, (
            "no approval was ever recorded"
        )
        assert review["disposition_approved_at"] is None, (
            f"disposition_approved_at must stay null, got {review['disposition_approved_at']}"
        )

        comment = scenario.get_comment(scenario.comment_id)
        assert comment["status"] == "OPEN", (
            f"the comment returns to OPEN, got {comment['status']}"
        )
        assert comment["disposition_rationale"] is None, (
            "the reopening clears the rationale, got "
            f"{comment['disposition_rationale']}"
        )


class TestSeatLedgerIsRestoredByAWithdrawal:
    """A withdrawn vote leaves the four seat counters exactly as they were."""

    def test_withdrawing_a_negative_returns_the_seat_with_no_tally_drift(self, api):
        """
        A withdrawn vote contributes to nothing: it leaves every position bucket, its
        seat returns to `not_returned_count`, and the four seat counters return to
        exactly the values they held before the vote was cast.

        Design: Difficulty/compensating_invariant/withdrawing_a_negative_vote_returns_the_seat_with_no_tally_drift
        """
        scenario = fx.open_subcommittee_ballot(api)
        a.assert_seat_ledger(
            scenario.get_ballot(),
            affirmative=0,
            negative=0,
            abstain=0,
            returned=0,
            not_returned=3,
            eligible=3,
        )

        scenario.cast("m1", "AFFIRMATIVE", vote_key="v1")
        scenario.cast_negative("m3", vote_key="v3")
        a.assert_seat_ledger(
            scenario.get_ballot(),
            affirmative=1,
            negative=1,
            abstain=0,
            returned=2,
            not_returned=1,
            eligible=3,
        )

        scenario.withdraw_vote("v3")

        ballot = scenario.get_ballot()
        a.assert_seat_ledger(
            ballot,
            affirmative=1,
            negative=0,
            abstain=0,
            returned=1,
            not_returned=2,
            eligible=3,
        )
        assert ballot["status"] == "OPEN", (
            f"the ballot is still open for voting, got {ballot['status']}"
        )
        vote = scenario.get_vote("v3")
        assert vote["status"] == "WITHDRAWN", (
            f"vote status expected WITHDRAWN, got {vote['status']}"
        )
        assert vote["adjudication_status"] == "NOT_APPLICABLE", (
            "a withdrawn negative never enters the adjudication dimension, got "
            f"{vote['adjudication_status']}"
        )

    def test_objection_behind_a_withdrawn_negative_stays_on_file(self, api):
        """
        it stays on file in `status` `OPEN` as the historical record of the objection,
        still carrying a null `public_review_id` and therefore still outside every
        disposition ledger.

        Design: Difficulty/compensating_invariant/withdrawing_a_negative_vote_returns_the_seat_with_no_tally_drift
        """
        scenario = fx.open_subcommittee_ballot(api)
        scenario.cast("m1", "AFFIRMATIVE", vote_key="v1")
        negative = scenario.cast_negative("m3", vote_key="v3")
        scenario.withdraw_vote("v3")

        comments, meta = validate_paginated(
            api.list_comments(scenario.staff, {"ballot_id": scenario.ballot_id})
        )
        a.assert_total_count(meta, 1)
        comment = comments[0]
        assert comment["status"] == "OPEN", (
            f"the objection stays OPEN on file, got {comment['status']}"
        )
        assert comment["source_type"] == "BALLOT_NEGATIVE", (
            f"source_type expected BALLOT_NEGATIVE, got {comment['source_type']}"
        )
        assert comment["source_vote_id"] == negative["id"], (
            "the comment points back at the vote it explained"
        )
        assert comment["public_review_id"] is None, (
            "a ballot objection is outside every disposition ledger, got "
            f"{comment['public_review_id']}"
        )
        assert scenario.get_draft()["status"] == "SUBCOMMITTEE_BALLOT", (
            "the draft is still out at ballot"
        )
