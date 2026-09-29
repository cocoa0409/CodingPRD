"""
The arithmetic of a close, read off ballots that are deliberately awkward: a
quorum failure sitting on top of perfect approval, abstentions pulling the two
denominators apart, a denominator frozen while its roster shrinks, a change
ratio just under the recirculation bar, and attendance that finally bites.
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx


def _five_seat_committee(api):
    """Five voting seats in five distinct categories on five distinct employers."""
    scenario = fx.Scenario(api)
    scenario.register_core()
    scenario.register("p4", interest_category="REGULATORY")
    scenario.register("p5", interest_category="ACADEMIC")
    scenario.create_committee("p1")
    for participant_key, seat_key in (
        ("p1", "m1"),
        ("p2", "m2"),
        ("p3", "m3"),
        ("p4", "m4"),
        ("p5", "m5"),
    ):
        scenario.appoint(participant_key, seat_key)
    scenario.activate_committee()
    return scenario


def _five_seat_ballot(api):
    """A five-seat committee whose revision-1 draft is out for a subcommittee ballot."""
    scenario = _five_seat_committee(api)
    scenario.propose_work_item("p1")
    scenario.approve_scope(designation="STD-1400")
    scenario.add_draft(total_clause_count=40, changed_clause_count=0)
    scenario.open_ballot()
    return scenario


class TestTheVerdictLadderIsOrdered:
    """The first matching branch wins, so quorum hides everything behind it."""

    def test_quorum_failure_masks_a_hundred_percent_approval(self, api):
        """
        A quorum failure therefore masks a threshold failure: a ballot that misses both
        bars reports `FAILED_QUORUM` only.

        Design: Corner/calculations/quorum_failure_masks_a_hundred_percent_approval_on_a_two_of_five_return
        """
        scenario = _five_seat_ballot(api)
        scenario.cast("m1", "AFFIRMATIVE", vote_key="v1")
        scenario.cast("m2", "ABSTAIN", vote_key="v2")
        scenario.set_clock("2026-08-15T00:00:00Z")

        scenario.close_ballot()

        ballot = scenario.get_ballot()
        a.assert_seat_ledger(
            ballot,
            affirmative=1,
            negative=0,
            abstain=1,
            returned=2,
            not_returned=3,
            eligible=5,
        )
        a.assert_pct(ballot["return_rate_pct"], 40.0)
        a.assert_pct(ballot["required_return_rate_pct"], 50.0)
        a.assert_pct(ballot["provisional_approval_pct"], 100.0)
        a.assert_pct(ballot["required_approval_pct"], 50.1)
        assert ballot["consensus_result"] == "FAILED_QUORUM", (
            "the approval bar is cleared, yet the quorum branch matches first; got "
            f"{ballot['consensus_result']}"
        )
        assert ballot["pending_negative_count"] == 0, (
            f"pending_negative_count expected 0, got {ballot['pending_negative_count']}"
        )
        a.assert_same_instant(ballot["closed_at"], "2026-08-15T00:00:00Z")
        assert scenario.get_draft()["status"] == "DRAFTING", (
            "a failed subcommittee ballot sends the text back for work, got "
            f"{scenario.get_draft()['status']}"
        )
        for seat_key in ("m3", "m4", "m5"):
            seat = scenario.get_membership(seat_key)
            assert seat["missed_ballot_streak"] == 1, (
                f"seat {seat_key} missed one ballot, got {seat['missed_ballot_streak']}"
            )
            assert seat["status"] == "ACTIVE", (
                f"one missed ballot is below the suspension streak, got {seat['status']}"
            )
        assert scenario.get_work_item()["consensus_gate"] == "OPEN", (
            "a failed ballot is not a procedural blocker"
        )


class TestTheTwoDenominators:
    """A return and an approval are counted over different input sets."""

    def test_abstentions_return_the_seat_but_leave_the_approval_base(self, api):
        """
        Second the percentages: `return_rate_pct` is 0.0 when `eligible_voter_count` is
        zero and otherwise 100 multiplied by `returned_count`, divided by
        `eligible_voter_count`, rounded half up to one decimal place; the approval base is
        `affirmative_count` plus `negative_count`, with abstentions deliberately excluded,
        and the approval percentage is 0.0 when that base is zero and otherwise 100
        multiplied by `affirmative_count`, divided by the base, rounded half up to one
        decimal place.

        Design: Corner/calculations/abstentions_count_as_returns_but_are_excluded_from_the_approval_base
        """
        scenario = _five_seat_ballot(api)
        scenario.cast("m1", "AFFIRMATIVE", vote_key="v1")
        scenario.cast("m2", "AFFIRMATIVE", vote_key="v2")
        scenario.cast_negative("m3", vote_key="v3")
        scenario.cast("m4", "ABSTAIN", vote_key="v4")
        scenario.cast("m5", "ABSTAIN", vote_key="v5")

        scenario.close_ballot()

        ballot = scenario.get_ballot()
        a.assert_seat_ledger(
            ballot,
            affirmative=2,
            negative=1,
            abstain=2,
            returned=5,
            not_returned=0,
            eligible=5,
        )
        a.assert_seat_conservation(ballot)
        a.assert_pct(ballot["return_rate_pct"], 100.0)
        a.assert_pct(ballot["provisional_approval_pct"], 66.7)
        assert ballot["consensus_result"] == "APPROVED_PENDING_NEGATIVES", (
            "two of the three counted seats approve, and one negative is pending; got "
            f"{ballot['consensus_result']}"
        )
        assert ballot["pending_negative_count"] == 1, (
            f"pending_negative_count expected 1, got {ballot['pending_negative_count']}"
        )
        assert scenario.get_draft()["status"] == "COMMENT_RESOLUTION", (
            f"the pending negative diverts the draft, got {scenario.get_draft()['status']}"
        )

    def test_a_seat_suspended_mid_ballot_never_shrinks_the_denominator(self, api):
        """
        The size of that set is written to `eligible_voter_count` and is frozen for the
        life of the ballot.

        Design: Corner/calculations/eligible_voter_count_stays_frozen_when_a_seat_is_suspended_mid_ballot
        """
        scenario = _five_seat_ballot(api)
        assert scenario.get_ballot()["eligible_voter_count"] == 5, (
            "the eligible set was frozen at five seats"
        )

        scenario.patch_membership("m5", status="SUSPENDED")

        committee = scenario.get_committee()
        assert committee["status"] == "ACTIVE", (
            "four seats in four categories still balance, got "
            f"{committee['status']}"
        )
        a.assert_voting_balance(
            committee,
            balance_status="BALANCED",
            active_member_count=4,
            distinct_category_count=4,
            dominance_pct=25.0,
        )

        for seat_key, vote_key in (
            ("m1", "v1"),
            ("m2", "v2"),
            ("m3", "v3"),
            ("m4", "v4"),
        ):
            scenario.cast(seat_key, "AFFIRMATIVE", vote_key=vote_key)
        scenario.set_clock("2026-08-15T00:00:00Z")
        scenario.close_ballot()

        ballot = scenario.get_ballot()
        assert ballot["eligible_voter_count"] == 5, (
            "the suspended seat stays in the frozen denominator, got "
            f"{ballot['eligible_voter_count']}"
        )
        a.assert_seat_ledger(
            ballot,
            affirmative=4,
            negative=0,
            abstain=0,
            returned=4,
            not_returned=1,
            eligible=5,
        )
        a.assert_pct(ballot["return_rate_pct"], 80.0)
        a.assert_pct(ballot["provisional_approval_pct"], 100.0)
        assert ballot["consensus_result"] == "APPROVED", (
            f"80.0 still clears the 50.0 bar, got {ballot['consensus_result']}"
        )
        assert ballot["pending_negative_count"] == 0, (
            f"pending_negative_count expected 0, got {ballot['pending_negative_count']}"
        )
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_READY", (
            f"the approved draft moves on, got {scenario.get_draft()['status']}"
        )


class TestTheRecirculationBoundary:
    """A change ratio under the threshold inherits rather than forces a kind."""

    def test_three_of_forty_clauses_inherits_the_predecessor_kind(self, api):
        """
        To make the boundary concrete: on a revision with 40 clauses in total, 4 changed
        clauses gives a ratio of exactly 0.1000 and forces recirculation, while 3 changed
        clauses gives 0.0750 and inherits the predecessor's kind.

        Design: Corner/calculations/three_of_forty_changed_clauses_stays_below_the_recirculation_threshold
        """
        scenario = fx.work_item_with_draft(api)
        first_draft_id = scenario.draft_id
        scenario.open_ballot()
        scenario.cast("m2", "ABSTAIN", vote_key="v2")
        scenario.cast("m3", "ABSTAIN", vote_key="v3")
        scenario.set_clock("2026-08-15T00:00:00Z")
        scenario.close_ballot()

        failed = scenario.get_ballot()
        a.assert_pct(failed["return_rate_pct"], 66.7)
        a.assert_pct(failed["provisional_approval_pct"], 0.0)
        assert failed["consensus_result"] == "FAILED_THRESHOLD", (
            "an empty approval base reads 0.0 percent, got "
            f"{failed['consensus_result']}"
        )
        assert failed["pending_negative_count"] == 0, (
            f"nobody voted against, got {failed['pending_negative_count']}"
        )
        assert scenario.get_draft(first_draft_id)["status"] == "DRAFTING", (
            "the failed ballot returned revision 1 for work"
        )

        revision_two = scenario.add_draft(
            total_clause_count=40,
            changed_clause_count=3,
            prior_draft_id=first_draft_id,
            summary="Revision 2 — three clauses edited",
        )

        assert revision_two["revision_number"] == 2, (
            f"revision_number expected 2, got {revision_two['revision_number']}"
        )
        a.assert_ratio(revision_two["substantive_change_ratio"], 0.0750)
        assert revision_two["prior_draft_id"] == first_draft_id, (
            "the successor names the revision it supersedes"
        )
        assert revision_two["status"] == "DRAFTING", (
            f"the successor opens in DRAFTING, got {revision_two['status']}"
        )
        assert revision_two["recirculation_required"] is False, (
            f"recirculation_required expected false, got {revision_two['recirculation_required']}"
        )
        assert scenario.get_draft(first_draft_id)["status"] == "ABANDONED", (
            "the superseded predecessor is abandoned, got "
            f"{scenario.get_draft(first_draft_id)['status']}"
        )

        successor_ballot = scenario.open_ballot(
            opens_at="2026-08-15T00:00:00Z", closes_at="2026-08-29T00:00:00Z"
        )

        assert successor_ballot["effective_ballot_kind"] == "SUBCOMMITTEE", (
            "0.0750 is under the threshold, so the predecessor's kind is inherited; got "
            f"{successor_ballot['effective_ballot_kind']}"
        )
        assert successor_ballot["eligible_voter_count"] == 3, (
            "the full active voting roster is polled, not the two prior returners; got "
            f"{successor_ballot['eligible_voter_count']}"
        )
        a.assert_pct(successor_ballot["required_approval_pct"], 50.1)
        a.assert_pct(successor_ballot["required_return_rate_pct"], 50.0)


class TestAttendanceFinallyBites:
    """One absence is a warning; the second one costs the seat and the committee."""

    def test_a_second_consecutive_absence_suspends_the_seat_and_topples_the_committee(
        self, api
    ):
        """
        Every eligible seat that returned no cast vote has its `missed_ballot_streak`
        incremented, and a seat whose streak reaches 2 is suspended by the system, moving
        from `ACTIVE` to `SUSPENDED`.

        Design: Corner/cross_cutting_complexity_layers/a_second_consecutive_missed_ballot_suspends_the_seat_and_topples_the_committee
        """
        scenario = fx.work_item_with_draft(api)
        scenario.open_ballot()
        scenario.cast("m1", "AFFIRMATIVE", vote_key="v1")
        scenario.set_clock("2026-08-15T00:00:00Z")
        scenario.close_ballot()

        first_round = scenario.get_ballot()
        a.assert_pct(first_round["return_rate_pct"], 33.3)
        assert first_round["consensus_result"] == "FAILED_QUORUM", (
            f"consensus_result expected FAILED_QUORUM, got {first_round['consensus_result']}"
        )
        for seat_key in ("m2", "m3"):
            seat = scenario.get_membership(seat_key)
            assert seat["missed_ballot_streak"] == 1, (
                f"seat {seat_key} expected streak 1, got {seat['missed_ballot_streak']}"
            )
            assert seat["status"] == "ACTIVE", (
                f"seat {seat_key} survives one absence, got {seat['status']}"
            )
        assert scenario.get_committee()["status"] == "ACTIVE", (
            "the committee is untouched by a single round of absence"
        )
        assert scenario.get_draft()["status"] == "DRAFTING", (
            f"the draft came back for work, got {scenario.get_draft()['status']}"
        )

        second_round = scenario.open_ballot(
            opens_at="2026-08-15T00:00:00Z", closes_at="2026-08-29T00:00:00Z"
        )
        scenario.cast("m1", "AFFIRMATIVE", vote_key="w1")
        scenario.set_clock("2026-08-29T00:00:00Z")

        scenario.close_ballot()

        closed = scenario.get_ballot(second_round["id"])
        assert closed["eligible_voter_count"] == 3, (
            "the seats this very close suspends do not shrink its denominator, got "
            f"{closed['eligible_voter_count']}"
        )
        a.assert_pct(closed["return_rate_pct"], 33.3)
        assert closed["consensus_result"] == "FAILED_QUORUM", (
            f"consensus_result expected FAILED_QUORUM, got {closed['consensus_result']}"
        )
        for seat_key in ("m2", "m3"):
            seat = scenario.get_membership(seat_key)
            assert seat["missed_ballot_streak"] == 2, (
                f"seat {seat_key} expected streak 2, got {seat['missed_ballot_streak']}"
            )
            assert seat["status"] == "SUSPENDED", (
                f"the streak reached 2, so seat {seat_key} is suspended, got {seat['status']}"
            )
        chair_seat = scenario.get_membership("m1")
        assert chair_seat["missed_ballot_streak"] == 0, (
            f"the seat that voted twice keeps a zero streak, got {chair_seat['missed_ballot_streak']}"
        )
        assert chair_seat["status"] == "ACTIVE", (
            f"the voting seat is untouched, got {chair_seat['status']}"
        )

        committee = scenario.get_committee()
        assert committee["active_member_count"] == 1, (
            f"active_member_count expected 1, got {committee['active_member_count']}"
        )
        assert committee["balance_status"] == "UNBALANCED", (
            f"one seat cannot balance, got {committee['balance_status']}"
        )
        assert committee["status"] == "SUSPENDED", (
            f"the committee follows its seats down, got {committee['status']}"
        )
        assert scenario.get_work_item()["consensus_gate"] == "BLOCKED", (
            "a suspended sponsoring committee shuts the gate"
        )
        draft = scenario.get_draft()
        assert draft["status"] == "DRAFTING", (
            f"the second failure also returns the draft, got {draft['status']}"
        )
        assert draft["ballot_round_count"] == 2, (
            "two ballots have been opened on this revision, got "
            f"{draft['ballot_round_count']}"
        )
