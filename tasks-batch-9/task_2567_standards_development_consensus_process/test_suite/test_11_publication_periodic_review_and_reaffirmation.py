"""
Life after publication: the five-year maintenance cycle, the evidence a
reaffirmation demands, the window the cycle is allowed to run in, and the two
ways a published standard can leave the register.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestTheMaintenanceCycleIsGenuinelyCyclic:
    """UNDER_PERIODIC_REVIEW is visited twice, the second time from REAFFIRMED."""

    def test_a_reaffirmed_standard_becomes_due_again_and_reopens(self, api):
        """
        The edge out of `REAFFIRMED` is what makes the cycle a genuine loop: a reaffirmed
        standard becomes due again five years after its reaffirmation and may be opened
        for review again, without limit.

        Design: Corner/state_machines/work_item_cycles_from_published_through_periodic_review_to_reaffirmed_and_back
        """
        scenario = fx.published_work_item(api)
        published = scenario.get_work_item()
        a.assert_same_instant(published["published_at"], "2026-09-15T00:00:00Z")
        a.assert_date_equals(published["periodic_review_due_date"], "2031-09-15")

        scenario.set_clock("2031-03-19T00:00:00Z")
        opened = scenario.periodic_review(action="OPEN_REVIEW")
        assert opened["progress_status"] == "UNDER_PERIODIC_REVIEW", (
            f"the window opening admits the review, got {opened['progress_status']}"
        )

        reaffirmation = scenario.open_ballot(
            ballot_kind="REAFFIRMATION",
            opens_at="2031-03-19T00:00:00Z",
            closes_at="2031-04-18T00:00:00Z",
        )
        assert reaffirmation["effective_ballot_kind"] == "REAFFIRMATION", (
            "a draft with no predecessor keeps the submitted kind, got "
            f"{reaffirmation['effective_ballot_kind']}"
        )
        assert reaffirmation["eligible_voter_count"] == 3, (
            f"eligible_voter_count expected 3, got {reaffirmation['eligible_voter_count']}"
        )
        a.assert_pct(reaffirmation["required_return_rate_pct"], 66.7)
        a.assert_pct(reaffirmation["required_approval_pct"], 66.7)
        for seat_key, vote_key in (("m1", "vr1"), ("m2", "vr2"), ("m3", "vr3")):
            scenario.cast(seat_key, "AFFIRMATIVE", vote_key=vote_key)
        scenario.close_ballot()

        closed = scenario.get_ballot()
        assert closed["status"] == "EVALUATED", (
            f"status expected EVALUATED, got {closed['status']}"
        )
        assert closed["consensus_result"] == "APPROVED", (
            f"consensus_result expected APPROVED, got {closed['consensus_result']}"
        )
        confirmed_draft = scenario.get_draft()
        assert confirmed_draft["status"] == "APPROVED", (
            "a reaffirmation ballot re-confirms the text through a self-loop, got "
            f"{confirmed_draft['status']}"
        )
        assert confirmed_draft["revision_number"] == 1, (
            "no new revision is produced, got "
            f"{confirmed_draft['revision_number']}"
        )

        reaffirmed = scenario.periodic_review(
            action="REAFFIRM", rationale="Text remains technically current"
        )
        assert reaffirmed["progress_status"] == "REAFFIRMED", (
            f"progress_status expected REAFFIRMED, got {reaffirmed['progress_status']}"
        )
        a.assert_same_instant(reaffirmed["last_periodic_action_at"], "2031-03-19T00:00:00Z")
        a.assert_date_equals(reaffirmed["periodic_review_due_date"], "2036-03-19")

        scenario.set_clock("2035-09-21T00:00:00Z")
        reopened = scenario.periodic_review(action="OPEN_REVIEW")

        assert reopened["progress_status"] == "UNDER_PERIODIC_REVIEW", (
            "the second cycle re-enters review from REAFFIRMED, got "
            f"{reopened['progress_status']}"
        )
        a.assert_date_equals(reopened["periodic_review_due_date"], "2036-03-19")
        a.assert_same_instant(reopened["published_at"], "2026-09-15T00:00:00Z")


class TestTheReaffirmEdgeDemandsItsEvidence:
    """A reaffirmation stands on an approved reaffirmation ballot, or not at all."""

    def test_reaffirm_waits_for_the_ballot_and_then_for_the_negative(self, api):
        """
        the work item's latest draft — the one with the highest `revision_number` — must
        carry at least one ballot whose `effective_ballot_kind` is `REAFFIRMATION`, whose
        `status` is `EVALUATED` and whose `consensus_result` is `APPROVED`, else
        `ERR_REAFFIRMATION_BALLOT_REQUIRED`. A ballot left at
        `APPROVED_PENDING_NEGATIVES` does not satisfy it, because reaffirmation on the
        strength of a ballot whose negatives were never considered would defeat the whole
        point.

        Design: Corner/state_machines/periodic_review_reaffirm_edge_is_guarded_by_an_approved_reaffirmation_ballot
        """
        scenario = fx.published_work_item(api)
        scenario.set_clock("2031-03-19T00:00:00Z")
        scenario.periodic_review(action="OPEN_REVIEW")

        no_ballot_yet = api.periodic_review(
            scenario.work_item_id,
            f.periodic_review_payload(
                action="REAFFIRM", rationale="First attempt, no ballot yet"
            ),
            scenario.staff,
        )
        validate_error(no_ballot_yet, "ERR_REAFFIRMATION_BALLOT_REQUIRED", 409)

        scenario.open_ballot(
            ballot_kind="REAFFIRMATION",
            opens_at="2031-03-19T00:00:00Z",
            closes_at="2031-04-18T00:00:00Z",
        )
        scenario.cast("m1", "AFFIRMATIVE", vote_key="vr1")
        scenario.cast("m2", "AFFIRMATIVE", vote_key="vr2")
        scenario.cast_negative("m3", vote_key="vr3")
        scenario.close_ballot()

        provisional = scenario.get_ballot()
        a.assert_pct(provisional["provisional_approval_pct"], 66.7)
        assert provisional["consensus_result"] == "APPROVED_PENDING_NEGATIVES", (
            "the close reads the ballot provisionally, got "
            f"{provisional['consensus_result']}"
        )
        assert provisional["pending_negative_count"] == 1, (
            f"pending_negative_count expected 1, got {provisional['pending_negative_count']}"
        )
        assert scenario.get_draft()["status"] == "APPROVED", (
            "no edge out of APPROVED is declared for a close, got "
            f"{scenario.get_draft()['status']}"
        )

        negative_pending = api.periodic_review(
            scenario.work_item_id,
            f.periodic_review_payload(
                action="REAFFIRM", rationale="Second attempt, negative still pending"
            ),
            scenario.staff,
        )
        validate_error(negative_pending, "ERR_REAFFIRMATION_BALLOT_REQUIRED", 409)
        assert scenario.get_work_item()["progress_status"] == "UNDER_PERIODIC_REVIEW", (
            "the refused reaffirmation left the work item under review"
        )

        scenario.adjudicate(
            "vr3",
            "NON_PERSUASIVE",
            adjudication_rationale=(
                "The cited ceiling was already reviewed in the original consensus ballot"
            ),
        )
        assert scenario.get_vote("vr3")["adjudication_status"] == "NON_PERSUASIVE", (
            "the negative has now been considered"
        )
        final = scenario.get_ballot()
        a.assert_pct(final["final_approval_pct"], 66.7)
        assert final["consensus_result"] == "APPROVED", (
            f"consensus_result expected APPROVED, got {final['consensus_result']}"
        )
        a.assert_pct(final["provisional_approval_pct"], 66.7)

        reaffirmed = scenario.periodic_review(
            action="REAFFIRM", rationale="Third attempt, ballot now APPROVED"
        )
        assert reaffirmed["progress_status"] == "REAFFIRMED", (
            f"the edge is finally open, got {reaffirmed['progress_status']}"
        )
        a.assert_date_equals(reaffirmed["periodic_review_due_date"], "2036-03-19")


class TestSuspensionAndRetirement:
    """An upheld appeal can suspend a live standard; withdrawal then retires it."""

    def test_the_suspend_standard_remedy_moves_the_work_item_not_the_ballot(self, api):
        """
        Under the `SUSPEND_STANDARD` remedy a work item in `PUBLISHED` or `REAFFIRMED`
        moves to `SUSPENDED` instead of the draft and consensus hops running.

        Design: Corner/state_machines/upheld_appeal_with_suspend_standard_remedy_moves_the_published_work_item_to_suspended
        """
        scenario = fx.published_work_item(api)
        consensus_ballot_id = scenario.ballot_id
        scenario.file_appeal(
            "p2",
            cited_ballot_id=consensus_ballot_id,
            grounds="VOTING_PROCEDURE_DEFECT",
            statement="The tally was announced before the window had ended",
        )

        accepted = scenario.decide_appeal(
            decision="ACCEPT_FOR_REVIEW",
            decision_rationale="The procedural claim is colourable",
        )
        assert accepted["status"] == "ACCEPTED_FOR_REVIEW", (
            f"status expected ACCEPTED_FOR_REVIEW, got {accepted['status']}"
        )
        under_appeal = scenario.get_work_item()
        assert under_appeal["consensus_gate"] == "BLOCKED", (
            "an appeal under review shuts the gate, got "
            f"{under_appeal['consensus_gate']}"
        )
        assert under_appeal["progress_status"] == "PUBLISHED", (
            "accepting the appeal for review moves nothing else, got "
            f"{under_appeal['progress_status']}"
        )

        upheld = scenario.decide_appeal(
            decision="UPHOLD",
            decision_rationale="The tally was announced two days early",
            remedy="SUSPEND_STANDARD",
        )

        assert upheld["status"] == "UPHELD", (
            f"status expected UPHELD, got {upheld['status']}"
        )
        assert upheld["remedy"] == "SUSPEND_STANDARD", (
            f"remedy expected SUSPEND_STANDARD, got {upheld['remedy']}"
        )
        suspended = scenario.get_work_item()
        assert suspended["progress_status"] == "SUSPENDED", (
            f"progress_status expected SUSPENDED, got {suspended['progress_status']}"
        )
        assert suspended["consensus_gate"] == "OPEN", (
            "the decided appeal is neither FILED nor ACCEPTED_FOR_REVIEW, got "
            f"{suspended['consensus_gate']}"
        )
        a.assert_same_instant(suspended["published_at"], "2026-09-15T00:00:00Z")
        ballot = scenario.get_ballot(consensus_ballot_id)
        assert ballot["status"] == "EVALUATED", (
            f"this remedy leaves the ballot intact, got {ballot['status']}"
        )
        assert ballot["consensus_result"] == "APPROVED", (
            f"consensus_result expected APPROVED, got {ballot['consensus_result']}"
        )
        assert scenario.get_draft()["status"] == "APPROVED", (
            "no draft hop runs under this remedy, got "
            f"{scenario.get_draft()['status']}"
        )

        scenario.set_clock("2031-03-19T00:00:00Z")
        withdrawn = scenario.periodic_review(
            action="WITHDRAW",
            rationale="Suspended standard superseded by a new work item",
        )

        assert withdrawn["progress_status"] == "WITHDRAWN", (
            "a suspended standard is retired by the same act, got "
            f"{withdrawn['progress_status']}"
        )
        a.assert_same_instant(
            withdrawn["last_periodic_action_at"], "2031-03-19T00:00:00Z"
        )

    def test_reaffirmation_past_grace_is_barred_while_withdrawal_is_not(self, api):
        """
        It is also the one periodic-review action never barred by the grace deadline: an
        overdue standard must always remain withdrawable, so
        `ERR_REAFFIRMATION_WINDOW_EXPIRED` applies to REAFFIRM alone, while
        `ERR_PERIODIC_REVIEW_NOT_DUE` guards the window opening for both.

        Design: Corner/errors/a_reaffirmation_one_day_past_the_grace_period_is_time_barred_while_withdrawal_is_not
        """
        scenario = fx.published_work_item(api)
        scenario.set_clock("2031-03-19T00:00:00Z")
        scenario.periodic_review(action="OPEN_REVIEW")
        scenario.set_clock("2031-10-01T00:00:00Z")
        scenario.open_ballot(
            ballot_kind="REAFFIRMATION",
            opens_at="2031-10-01T00:00:00Z",
            closes_at="2031-10-31T00:00:00Z",
        )
        for seat_key, vote_key in (("m1", "vr1"), ("m2", "vr2"), ("m3", "vr3")):
            scenario.cast(seat_key, "AFFIRMATIVE", vote_key=vote_key)
        scenario.close_ballot()
        evidence = scenario.get_ballot()
        assert evidence["effective_ballot_kind"] == "REAFFIRMATION", (
            f"effective_ballot_kind expected REAFFIRMATION, got {evidence['effective_ballot_kind']}"
        )
        a.assert_pct(evidence["required_return_rate_pct"], 66.7)
        a.assert_pct(evidence["required_approval_pct"], 66.7)
        assert evidence["status"] == "EVALUATED", (
            f"status expected EVALUATED, got {evidence['status']}"
        )
        assert evidence["consensus_result"] == "APPROVED", (
            f"consensus_result expected APPROVED, got {evidence['consensus_result']}"
        )
        assert scenario.get_draft()["status"] == "APPROVED", (
            "a reaffirmation ballot never sends the draft back"
        )

        scenario.set_clock("2031-12-15T00:00:00Z")

        too_late = api.periodic_review(
            scenario.work_item_id,
            f.periodic_review_payload(
                action="REAFFIRM",
                rationale="The committee confirms the standard without change",
            ),
            scenario.staff,
        )
        validate_error(too_late, "ERR_REAFFIRMATION_WINDOW_EXPIRED", 409)

        barred = scenario.get_work_item()
        assert barred["progress_status"] == "UNDER_PERIODIC_REVIEW", (
            f"the refusal moved nothing, got {barred['progress_status']}"
        )
        a.assert_date_equals(barred["periodic_review_due_date"], "2031-09-15")

        withdrawn = scenario.periodic_review(
            action="WITHDRAW",
            rationale="Reaffirmation lapsed; the standard is withdrawn",
        )

        assert withdrawn["progress_status"] == "WITHDRAWN", (
            "the same instant admits a withdrawal, got "
            f"{withdrawn['progress_status']}"
        )
        a.assert_same_instant(
            withdrawn["last_periodic_action_at"], "2031-12-15T00:00:00Z"
        )
        assert withdrawn["periodic_review_due_date"] is None, (
            "withdrawal sets the due date to null, got "
            f"{withdrawn['periodic_review_due_date']}"
        )


class TestTheWindowsLowerBound:
    """The review window opens on a closed bound 180 days before the due date."""

    def test_the_window_opens_exactly_one_hundred_eighty_days_before_the_due_date(
        self, api
    ):
        """
        So a standard published on 2026-09-15 is due for review on 2031-09-15, may be
        opened for review from 2031-03-19, and may be reaffirmed up to and including
        2031-12-14.

        Design: Corner/calculations/periodic_review_opens_exactly_one_hundred_eighty_days_before_the_due_date
        """
        scenario = fx.published_work_item(api)
        published = scenario.get_work_item()
        a.assert_same_instant(published["published_at"], "2026-09-15T00:00:00Z")
        a.assert_date_equals(published["periodic_review_due_date"], "2031-09-15")

        scenario.set_clock("2031-03-18T00:00:00Z")
        one_day_early = api.periodic_review(
            scenario.work_item_id,
            f.periodic_review_payload(
                action="OPEN_REVIEW", rationale="Opening the five-year review"
            ),
            scenario.staff,
        )
        validate_error(one_day_early, "ERR_PERIODIC_REVIEW_NOT_DUE", 409)

        refused = scenario.get_work_item()
        assert refused["progress_status"] == "PUBLISHED", (
            f"the refused action moved nothing, got {refused['progress_status']}"
        )
        assert refused["last_periodic_action_at"] is None, (
            "a refused action writes no timestamp, got "
            f"{refused['last_periodic_action_at']}"
        )
        a.assert_version_unchanged(published, refused)

        scenario.set_clock("2031-03-19T00:00:00Z")
        opened = scenario.periodic_review(
            action="OPEN_REVIEW", rationale="Opening the five-year review"
        )

        assert opened["progress_status"] == "UNDER_PERIODIC_REVIEW", (
            "the bound is closed, so the opening day itself is in window, got "
            f"{opened['progress_status']}"
        )
        a.assert_same_instant(opened["last_periodic_action_at"], "2031-03-19T00:00:00Z")
        a.assert_date_equals(opened["periodic_review_due_date"], "2031-09-15")
