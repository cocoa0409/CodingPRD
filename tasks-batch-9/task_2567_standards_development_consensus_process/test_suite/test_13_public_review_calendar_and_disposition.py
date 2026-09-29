"""
The public-review calendar and the disposition ledger it feeds: the inclusive
45-day floor, the version token a caller must have re-read, the closed final day,
the completeness percentage, its approval, and the reopen that undoes it.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestTheInclusiveWindowFloor:
    """Forty-five days counted inclusively is the shortest admissible review."""

    def test_forty_four_days_is_refused_and_the_next_day_is_accepted(self, api):
        """
        A window from 2026-08-01 to 2026-09-14 is 45 days inclusive and is accepted, while
        the same window ending 2026-09-13 is 44 days and is refused with
        `ERR_REVIEW_PERIOD_TOO_SHORT`.

        Design: Corner/calculations/forty_four_day_public_review_is_rejected_and_forty_five_days_is_accepted
        """
        scenario = fx.draft_ready_for_public_review(api)
        before = scenario.get_draft()
        assert before["status"] == "PUBLIC_REVIEW_READY", (
            f"the approved draft is ready for review, got {before['status']}"
        )
        pinned_version = before["version"]

        too_short = api.create_public_review(
            f.public_review_payload(
                scenario.draft_id,
                pinned_version,
                start_date="2026-08-01",
                end_date="2026-09-13",
            ),
            scenario.staff,
        )
        validate_error(too_short, "ERR_REVIEW_PERIOD_TOO_SHORT", 409)

        rows, meta = validate_paginated(api.list_public_reviews(scenario.staff))
        a.assert_total_count(meta, 0)
        assert rows == [], f"the refused announcement created no row, got {rows}"
        refused = scenario.get_draft()
        assert refused["status"] == "PUBLIC_REVIEW_READY", (
            f"the draft is untouched by the refusal, got {refused['status']}"
        )
        a.assert_version_unchanged(before, refused)

        review = scenario.announce_public_review(
            start_date="2026-08-01",
            end_date="2026-09-14",
            expected_draft_version=pinned_version,
        )

        a.assert_has_fields(review, "PublicReview")
        assert review["duration_days"] == 45, (
            "both endpoints are counted, so the window is 45 days, got "
            f"{review['duration_days']}"
        )
        assert review["status"] == "OPEN", (
            "the clock has already reached the start date, got "
            f"{review['status']}"
        )
        a.assert_comment_ledger(
            review,
            comment_count=0,
            disposed_count=0,
            unresolved_count=0,
            completeness_pct=100.0,
        )
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW", (
            f"the accepted announcement moves the draft, got {scenario.get_draft()['status']}"
        )


class TestTheVersionTokenMustBeFresh:
    """A version read before the close cascade touched the draft is stale."""

    def test_a_version_read_before_the_ballot_close_is_rejected(self, api):
        """
        When `expected_draft_version` does not equal the draft's stored `version`, the
        request is rejected with `ERR_STALE_DRAFT_VERSION` (HTTP 412), no public review row
        is created, and nothing is cancelled, so a stale announcement can never cancel a
        review its caller never saw.

        Design: Corner/cross_cutting_complexity_layers/a_draft_version_observed_before_the_ballot_close_is_rejected_as_stale
        """
        scenario = fx.unanimous_subcommittee_ballot(api)
        observed_while_open = scenario.get_draft()
        stale_version = observed_while_open["version"]

        scenario.close_ballot()
        assert scenario.get_ballot()["consensus_result"] == "APPROVED", (
            "the unanimous ballot passed, so the cascade reached the draft"
        )

        stale = api.create_public_review(
            f.public_review_payload(
                scenario.draft_id,
                stale_version,
                start_date="2026-08-01",
                end_date="2026-09-14",
            ),
            scenario.staff,
        )
        validate_error(stale, "ERR_STALE_DRAFT_VERSION", 412)

        rows, meta = validate_paginated(api.list_public_reviews(scenario.staff))
        a.assert_total_count(meta, 0)
        assert rows == [], f"the rejected announcement created no row, got {rows}"
        refused = scenario.get_draft()
        assert refused["status"] == "PUBLIC_REVIEW_READY", (
            f"the draft keeps the state the close gave it, got {refused['status']}"
        )
        fresh_version = refused["version"]
        assert fresh_version > stale_version, (
            "the close cascade advanced the draft past the observed version: "
            f"{fresh_version} is not greater than {stale_version}"
        )

        review = scenario.announce_public_review(
            start_date="2026-08-01",
            end_date="2026-09-14",
            expected_draft_version=fresh_version,
        )

        assert review["status"] == "OPEN", (
            f"the identical body succeeds on the re-read token, got {review['status']}"
        )
        assert review["duration_days"] == 45, (
            f"duration_days expected 45, got {review['duration_days']}"
        )
        assert review["draft_id"] == scenario.draft_id, (
            "the review names the draft it was announced against"
        )
        accepted = scenario.get_draft()
        assert accepted["status"] == "PUBLIC_REVIEW", (
            f"the draft moves only on the accepted call, got {accepted['status']}"
        )
        assert accepted["version"] == fresh_version + 1, (
            "the announcement advanced the draft exactly once, got "
            f"{accepted['version']} against {fresh_version}"
        )


class TestTheFinalDayIsStillRunning:
    """The end date is a closed bound, so the close waits for it to elapse."""

    def test_closing_inside_the_last_day_is_refused_and_then_fast_paths(self, api):
        """
        since the last day of an inclusive window must be fully elapsed; otherwise the
        response is `ERR_REVIEW_NOT_ENDED`. The close records `closed_at`, freezes
        `comment_count`, recomputes the disposition counters, moves the review from `OPEN`
        to `CLOSED`, and moves the parent draft from `PUBLIC_REVIEW` to
        `PUBLIC_REVIEW_CLOSED`, advancing both `version` values.

        Design: Corner/validations/closing_a_public_review_during_its_final_day_is_refused_as_not_ended
        """
        scenario = fx.draft_ready_for_public_review(api)
        announced = scenario.announce_public_review(
            start_date="2026-08-01", end_date="2026-09-14"
        )
        assert announced["status"] == "OPEN", (
            f"the review is open for its whole window, got {announced['status']}"
        )

        scenario.set_clock("2026-09-14T12:00:00Z")
        premature = api.close_public_review(scenario.public_review_id, scenario.staff)
        validate_error(premature, "ERR_REVIEW_NOT_ENDED", 409)

        still_open = scenario.get_public_review()
        assert still_open["status"] == "OPEN", (
            "midday on the final day is still inside the window, got "
            f"{still_open['status']}"
        )
        assert still_open["closed_at"] is None, (
            f"the refused close wrote no timestamp, got {still_open['closed_at']}"
        )
        a.assert_version_unchanged(announced, still_open)
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW", (
            f"the draft is still out for review, got {scenario.get_draft()['status']}"
        )

        scenario.set_clock("2026-09-15T00:00:00Z")
        closed = scenario.close_public_review()

        a.assert_same_instant(closed["closed_at"], "2026-09-15T00:00:00Z")
        a.assert_comment_ledger(
            closed,
            comment_count=0,
            disposed_count=0,
            unresolved_count=0,
            completeness_pct=100.0,
        )
        assert closed["status"] == "DISPOSITION_APPROVED", (
            "a review with nothing to dispose skips DISPOSITION_DRAFTED entirely, got "
            f"{closed['status']}"
        )
        a.assert_same_instant(closed["disposition_approved_at"], "2026-09-15T00:00:00Z")
        assert closed["disposition_approved_by_participant_id"] is None, (
            "nobody approved the empty record, got "
            f"{closed['disposition_approved_by_participant_id']}"
        )
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_CLOSED", (
            f"the parent draft follows the close, got {scenario.get_draft()['status']}"
        )


class TestTheCompletenessPercentage:
    """One of three answered comments reads 33.3 and bubbles nothing up."""

    def test_one_of_three_disposed_reads_thirty_three_point_three(self, api):
        """
        And `disposition_completeness_pct` is 100.0 when `comment_count` is zero, and
        otherwise 100 multiplied by `disposed_count`, divided by `comment_count`, rounded
        half up to one decimal place.

        Design: Corner/calculations/one_of_three_disposed_comments_gives_thirty_three_point_three_completeness
        """
        scenario = fx.draft_ready_for_public_review(api)
        scenario.register("p6")
        scenario.announce_public_review(start_date="2026-08-01", end_date="2026-09-14")
        first = scenario.submit_public_comment(
            "p6",
            comment_type="TECHNICAL",
            comment_text="The torque band in clause 9 is too wide for cast fittings",
            clause_reference="9",
        )
        scenario.submit_public_comment(
            "p2",
            comment_type="GENERAL",
            comment_text="The scope statement should say which fittings are excluded",
            clause_reference="1",
        )
        scenario.submit_public_comment(
            "p3",
            comment_type="EDITORIAL",
            comment_text="Clause numbering skips from 11 to 13",
            clause_reference="11",
        )
        scenario.set_clock("2026-09-15T00:00:00Z")
        closed = scenario.close_public_review()
        a.assert_comment_ledger(
            closed,
            comment_count=3,
            disposed_count=0,
            unresolved_count=3,
            completeness_pct=0.0,
        )

        scenario.dispose_comment(
            first["id"],
            disposition="ACCEPTED_WITH_MODIFICATION",
            disposition_rationale="A tolerance band is added with a narrower range",
        )

        assert scenario.get_comment(first["id"])["status"] == "ACCEPTED_WITH_MODIFICATION", (
            "the first comment carries its disposition, got "
            f"{scenario.get_comment(first['id'])['status']}"
        )
        review = scenario.get_public_review()
        a.assert_comment_ledger(
            review,
            comment_count=3,
            disposed_count=1,
            unresolved_count=2,
            completeness_pct=33.3,
        )
        a.assert_comment_ledger_conservation(review)
        assert review["status"] == "CLOSED", (
            "two comments are still open, so nothing bubbles up; got "
            f"{review['status']}"
        )


def _fully_disposed_review(api):
    """
    A closed public review carrying one technical and one general comment, both
    answered by the chair, so the review has bubbled up to DISPOSITION_DRAFTED at
    100.0 completeness with the clock at 2026-09-15T00:00:00Z.
    """
    scenario = fx.draft_ready_for_public_review(api)
    scenario.register("p6")
    scenario.announce_public_review(start_date="2026-08-01", end_date="2026-09-14")
    technical = scenario.submit_public_comment(
        "p6",
        comment_type="TECHNICAL",
        comment_text="The torque band in clause 9 is too wide for cast fittings",
        clause_reference="9",
    )
    general = scenario.submit_public_comment(
        "p2",
        comment_type="GENERAL",
        comment_text="The scope statement should say which fittings are excluded",
        clause_reference="1",
    )
    scenario.set_clock("2026-09-15T00:00:00Z")
    scenario.close_public_review()
    scenario.dispose_comment(
        technical["id"],
        disposition="ACCEPTED_WITH_MODIFICATION",
        disposition_rationale="A tolerance band is added with a narrower range",
    )
    scenario.dispose_comment(
        general["id"],
        disposition="REJECTED",
        disposition_rationale="The scope statement already excludes cast fittings",
    )
    return scenario, technical, general


class TestApprovingTheDispositionRecord:
    """A fully answered record satisfies the completeness guard and terminates."""

    def test_a_fully_disposed_review_reaches_the_terminal_state(self, api):
        """
        On success the review moves from `DISPOSITION_DRAFTED` to the terminal
        `DISPOSITION_APPROVED`, `disposition_approved_at` is taken from the logical clock,
        and `disposition_approved_by_participant_id` records the caller's identifier when
        the caller is a chair and stays null when the caller is the opaque secretariat role.

        Design: Corner/validations/approving_a_fully_disposed_review_satisfies_the_completeness_guard
        """
        scenario, _technical, _general = _fully_disposed_review(api)
        drafted = scenario.get_public_review()
        assert drafted["status"] == "DISPOSITION_DRAFTED", (
            "the last disposition bubbled the review up, got "
            f"{drafted['status']}"
        )
        a.assert_comment_ledger(
            drafted,
            comment_count=2,
            disposed_count=2,
            unresolved_count=0,
            completeness_pct=100.0,
        )

        approved = scenario.approve_disposition()

        a.assert_comment_ledger(
            approved,
            comment_count=2,
            disposed_count=2,
            unresolved_count=0,
            completeness_pct=100.0,
        )
        assert approved["status"] == "DISPOSITION_APPROVED", (
            "exactly 100.0 completeness satisfies the guard, got "
            f"{approved['status']}"
        )
        a.assert_same_instant(approved["disposition_approved_at"], "2026-09-15T00:00:00Z")
        assert approved["disposition_approved_by_participant_id"] is None, (
            "the opaque secretariat leaves the approver null, got "
            f"{approved['disposition_approved_by_participant_id']}"
        )
        assert approved["disposition_approved_by_participant_id"] != scenario.pid("p1"), (
            "the sponsoring chair never signs off their own dispositions"
        )
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_CLOSED", (
            f"no disposition moves the draft, got {scenario.get_draft()['status']}"
        )

    def test_a_reopen_puts_the_state_check_in_front_of_the_completeness_check(self, api):
        """
        `REOPENED` is the exact compensation for all three. It returns a comment in
        `ACCEPTED`, `ACCEPTED_WITH_MODIFICATION` or `REJECTED` back to `OPEN`, clears its
        `disposition_rationale` to null, decrements the review's `disposed_count`,
        increments its `unresolved_comment_count`, recomputes
        `disposition_completeness_pct`, and reverses the earlier bubble-up by moving the
        review from `DISPOSITION_DRAFTED` back to `CLOSED` if it had already bubbled.

        Design: Corner/validations/reopening_a_disposed_comment_makes_the_state_check_intercept_the_completeness_check
        """
        scenario, technical, _general = _fully_disposed_review(api)
        assert scenario.get_public_review()["status"] == "DISPOSITION_DRAFTED", (
            "the record was complete before the reopen"
        )

        scenario.dispose_comment(
            technical["id"], disposition="REOPENED", disposition_rationale=None
        )

        response = api.approve_disposition(scenario.public_review_id, scenario.staff)
        validate_error(response, "ERR_INVALID_PUBLIC_REVIEW_STATE", 409)

        reopened = scenario.get_comment(technical["id"])
        assert reopened["status"] == "OPEN", (
            f"the compensation returned the comment to OPEN, got {reopened['status']}"
        )
        assert reopened["disposition_rationale"] is None, (
            "the reopen cleared the rationale, got "
            f"{reopened['disposition_rationale']}"
        )
        review = scenario.get_public_review()
        assert review["status"] == "CLOSED", (
            "the bubble-up was reversed, so the state check bites first; got "
            f"{review['status']}"
        )
        a.assert_comment_ledger(
            review,
            comment_count=2,
            disposed_count=1,
            unresolved_count=1,
            completeness_pct=50.0,
        )
        a.assert_comment_ledger_conservation(review)
        assert review["disposition_approved_by_participant_id"] is None, (
            "the refused approval recorded no approver, got "
            f"{review['disposition_approved_by_participant_id']}"
        )
        assert review["disposition_approved_at"] is None, (
            f"the refused approval wrote no timestamp, got {review['disposition_approved_at']}"
        )
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_CLOSED", (
            f"the draft is untouched throughout, got {scenario.get_draft()['status']}"
        )
