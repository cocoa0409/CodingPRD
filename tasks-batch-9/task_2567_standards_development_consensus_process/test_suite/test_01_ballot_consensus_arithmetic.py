"""
Consensus arithmetic on a ballot: the provisional reading taken at close, the
final reading taken after adjudication, the thresholds selected by the effective
ballot kind, and the two state dimensions a vote carries at once.
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx


class TestProvisionalAndFinalReadings:
    """The close reads positions as cast; adjudication re-reads them rewritten."""

    def test_persuasive_ruling_writes_a_final_approval_beside_the_provisional_one(
        self, api
    ):
        """
        The final reading re-runs the same four evaluation steps over the rewritten
        positions, writes the outcome to `final_approval_pct`, and preserves
        `provisional_approval_pct` untouched as the historical record of what the
        ballot looked like as cast.

        Design: Difficulty/dual_variant_calc/ballot_provisional_close_vs_final_adjudicated_approval_divergence
        """
        scenario = fx.evaluated_ballot_with_pending_negative(api)

        at_close = scenario.get_ballot()
        a.assert_pct(at_close["provisional_approval_pct"], 66.7)
        assert at_close["final_approval_pct"] is None, (
            "final_approval_pct stays null until an adjudication re-reads the ballot"
        )

        scenario.adjudicate(
            "v3", "PERSUASIVE", adjudication_rationale="Clause 12 will be re-drafted"
        )

        ballot = scenario.get_ballot()
        a.assert_pct(ballot["provisional_approval_pct"], 66.7)
        a.assert_pct(ballot["final_approval_pct"], 100.0)
        a.assert_pct(ballot["required_approval_pct"], 50.1)
        a.assert_seat_ledger(
            ballot,
            affirmative=3,
            negative=0,
            abstain=0,
            returned=3,
            not_returned=0,
            eligible=3,
        )
        assert ballot["pending_negative_count"] == 0, (
            "the ruled negative is no longer pending"
        )
        assert ballot["consensus_result"] == "APPROVED", (
            f"consensus_result should refresh to APPROVED, got {ballot['consensus_result']}"
        )

    def test_persuasive_ruling_rewrites_the_vote_and_reopens_development(self, api):
        """
        `PERSUASIVE` moves the vote's `adjudication_status` to `PERSUASIVE` and
        rewrites its `position` from `NEGATIVE` to `AFFIRMATIVE`, and sets the
        linked comment behind that vote to `ACCEPTED`.

        Design: Difficulty/dual_variant_calc/ballot_provisional_close_vs_final_adjudicated_approval_divergence
        """
        scenario = fx.evaluated_ballot_with_pending_negative(api)
        scenario.adjudicate(
            "v3", "PERSUASIVE", adjudication_rationale="Clause 12 will be re-drafted"
        )

        vote = scenario.get_vote("v3")
        assert vote["adjudication_status"] == "PERSUASIVE", (
            f"adjudication_status expected PERSUASIVE, got {vote['adjudication_status']}"
        )
        assert vote["position"] == "AFFIRMATIVE", (
            f"a persuasive negative is rewritten to AFFIRMATIVE, got {vote['position']}"
        )
        assert vote["status"] == "CAST", "the return dimension is untouched by a ruling"

        draft = scenario.get_draft()
        assert draft["status"] == "DRAFTING", (
            f"a persuasive ruling sends the draft back to DRAFTING, got {draft['status']}"
        )
        assert draft["recirculation_required"] is True, (
            "recirculation_required is set on the persuasive edge"
        )


class TestConsensusBodyThresholds:
    """Rounding happens before the comparison, and equality passes."""

    def test_consensus_ballot_rounds_the_approval_before_comparing_the_bar(self, api):
        """
        Two returns out of three seats is 66.666… percent, which sits below a 66.7
        percent quorum bar when left unrounded but is exactly equal to it once
        rounded — and every threshold comparison in this specification is
        inclusive, so equality passes.

        Design: Difficulty/combinatorial_formula/consensus_ballot_rounds_approval_before_comparing_threshold
        """
        scenario = fx.voted_consensus_ballot(api)
        scenario.close_ballot()

        ballot = scenario.get_ballot()
        assert ballot["effective_ballot_kind"] == "CONSENSUS_BODY", (
            f"effective kind expected CONSENSUS_BODY, got {ballot['effective_ballot_kind']}"
        )
        a.assert_seat_ledger(
            ballot,
            affirmative=2,
            negative=1,
            abstain=0,
            returned=3,
            not_returned=0,
            eligible=3,
        )
        a.assert_pct(ballot["return_rate_pct"], 100.0)
        a.assert_pct(ballot["required_return_rate_pct"], 66.7)
        a.assert_pct(ballot["provisional_approval_pct"], 66.7)
        a.assert_pct(ballot["required_approval_pct"], 66.7)
        assert ballot["final_approval_pct"] is None, (
            "the close leaves final_approval_pct null"
        )
        assert ballot["consensus_result"] == "APPROVED_PENDING_NEGATIVES", (
            "an approval exactly at the bar with one pending negative lands on "
            f"APPROVED_PENDING_NEGATIVES, got {ballot['consensus_result']}"
        )
        assert ballot["pending_negative_count"] == 1, (
            f"pending_negative_count expected 1, got {ballot['pending_negative_count']}"
        )

    def test_pending_negative_routes_the_draft_to_comment_resolution_and_shuts_the_gate(
        self, api
    ):
        """
        if the evaluated ballot leaves any pending negative, the draft goes to
        `COMMENT_RESOLUTION` regardless of `consensus_result`

        Design: Difficulty/combinatorial_formula/consensus_ballot_rounds_approval_before_comparing_threshold
        """
        scenario = fx.voted_consensus_ballot(api)
        scenario.close_ballot()

        draft = scenario.get_draft()
        assert draft["status"] == "COMMENT_RESOLUTION", (
            f"draft expected COMMENT_RESOLUTION, got {draft['status']}"
        )

        work_item = scenario.get_work_item()
        assert work_item["consensus_gate"] == "BLOCKED", (
            "a draft in COMMENT_RESOLUTION holds the gate shut, got "
            f"{work_item['consensus_gate']}"
        )
        assert work_item["unresolved_negative_count"] == 1, (
            f"unresolved_negative_count expected 1, got {work_item['unresolved_negative_count']}"
        )
        assert work_item["progress_status"] == "IN_DEVELOPMENT", (
            "an approval pending negatives does not advance the work item, got "
            f"{work_item['progress_status']}"
        )


class TestRecirculationKindAndEligibleSet:
    """The change ratio picks the kind, and only then is the voter set frozen."""

    def test_ten_percent_change_ratio_forces_recirculation_thresholds(self, api):
        """
        on a revision with 40 clauses in total, 4 changed clauses gives a ratio of
        exactly 0.1000 and forces recirculation, while 3 changed clauses gives
        0.0750 and inherits the predecessor's kind.

        Design: Difficulty/combinatorial_formula/recirculation_kind_resolved_before_eligible_voter_set_is_frozen
        """
        scenario = fx.revision_two_after_failed_subcommittee_ballot(api)
        first_ballot_id = scenario.ballot_ids[0]
        revision_two_id = scenario.draft_ids[1]

        revision_two = scenario.get_draft(revision_two_id)
        a.assert_ratio(revision_two["substantive_change_ratio"], 0.1000)
        assert revision_two["revision_number"] == 2, (
            f"revision_number expected 2, got {revision_two['revision_number']}"
        )

        ballot = scenario.open_ballot(
            draft_id=revision_two_id,
            ballot_kind="SUBCOMMITTEE",
            opens_at="2026-08-15T00:00:00Z",
            closes_at="2026-08-29T00:00:00Z",
            predecessor_ballot_id=first_ballot_id,
        )
        assert ballot["ballot_kind"] == "SUBCOMMITTEE", (
            "the submitted kind is recorded as the chair asked for it, got "
            f"{ballot['ballot_kind']}"
        )
        assert ballot["effective_ballot_kind"] == "RECIRCULATION", (
            "a ratio at 0.1000 overrides the submitted kind, got "
            f"{ballot['effective_ballot_kind']}"
        )
        a.assert_pct(ballot["required_approval_pct"], 75.0)
        a.assert_pct(ballot["required_return_rate_pct"], 66.7)

    def test_recirculation_polls_only_the_seats_that_voted_last_round(self, api):
        """
        For a recirculation, the eligible set is narrower and is the union of two
        groups: every seat that holds a cast vote on the predecessor ballot, plus
        every seat that is currently `ACTIVE` with `voting_rights` true and whose
        `appointed_at` is later than the predecessor ballot's `closes_at`.

        Design: Difficulty/combinatorial_formula/recirculation_kind_resolved_before_eligible_voter_set_is_frozen
        """
        scenario = fx.revision_two_after_failed_subcommittee_ballot(api)
        first_ballot_id = scenario.ballot_ids[0]

        predecessor = scenario.get_ballot(first_ballot_id)
        assert predecessor["consensus_result"] == "FAILED_THRESHOLD", (
            "the first round missed the 50.1 bar at 50.0, got "
            f"{predecessor['consensus_result']}"
        )
        assert predecessor["eligible_voter_count"] == 3, (
            "the first round polled the whole active voting roster"
        )
        superseded = scenario.get_draft(scenario.draft_ids[0])
        assert superseded["status"] == "ABANDONED", (
            f"a superseded predecessor is terminal, got {superseded['status']}"
        )

        ballot = scenario.open_ballot(
            draft_id=scenario.draft_ids[1],
            ballot_kind="SUBCOMMITTEE",
            opens_at="2026-08-15T00:00:00Z",
            closes_at="2026-08-29T00:00:00Z",
            predecessor_ballot_id=first_ballot_id,
        )
        assert ballot["eligible_voter_count"] == 2, (
            "only the two seats that returned last round are re-polled, got "
            f"{ballot['eligible_voter_count']}"
        )
        a.assert_seat_ledger(
            ballot,
            affirmative=0,
            negative=0,
            abstain=0,
            returned=0,
            not_returned=2,
            eligible=2,
        )


class TestDraftCyclesBackForASecondRound:
    """A persuasive negative sends the text back and a fresh round follows."""

    def test_second_round_reuses_the_same_revision_and_counts_the_round(self, api):
        """
        A persuasive negative therefore forces a substantive revision and the draft
        re-enters development, which is exactly the loop the change-ratio rule of
        §3.3 then re-prices.

        Design: Difficulty/non_linear_state_machine/draft_cycles_back_through_drafting_into_a_second_ballot_round
        """
        scenario = fx.evaluated_ballot_with_pending_negative(api)
        scenario.adjudicate(
            "v3", "PERSUASIVE", adjudication_rationale="Clause 12 will be re-drafted"
        )

        back_in_drafting = scenario.get_draft()
        assert back_in_drafting["status"] == "DRAFTING", (
            f"draft expected DRAFTING, got {back_in_drafting['status']}"
        )
        assert back_in_drafting["ballot_round_count"] == 1, (
            "one round has been opened on this revision so far, got "
            f"{back_in_drafting['ballot_round_count']}"
        )
        assert back_in_drafting["unresolved_negative_count"] == 0, (
            "the ruling cleared the last pending negative"
        )

        scenario.open_ballot(
            opens_at="2026-08-15T00:00:00Z", closes_at="2026-08-29T00:00:00Z"
        )

        draft = scenario.get_draft()
        assert draft["status"] == "SUBCOMMITTEE_BALLOT", (
            f"the same revision re-enters ballot, got {draft['status']}"
        )
        assert draft["revision_number"] == 1, (
            "cycling through DRAFTING does not mint a new revision, got "
            f"{draft['revision_number']}"
        )
        assert draft["ballot_round_count"] == 2, (
            f"ballot_round_count expected 2, got {draft['ballot_round_count']}"
        )
        assert scenario.get_ballot(scenario.ballot_ids[0])["status"] == "EVALUATED", (
            "the first round stays evaluated"
        )
        assert scenario.get_ballot()["status"] == "OPEN", "the second round is open"

    def test_second_round_on_a_revision_one_draft_keeps_the_submitted_kind(self, api):
        """
        If the draft has no `prior_draft_id`, the effective kind is exactly the
        submitted `ballot_kind`.

        Design: Difficulty/non_linear_state_machine/draft_cycles_back_through_drafting_into_a_second_ballot_round
        """
        scenario = fx.evaluated_ballot_with_pending_negative(api)
        scenario.adjudicate(
            "v3", "PERSUASIVE", adjudication_rationale="Clause 12 will be re-drafted"
        )
        assert scenario.get_draft()["recirculation_required"] is True, (
            "the persuasive edge left the recirculation flag raised"
        )

        ballot = scenario.open_ballot(
            opens_at="2026-08-15T00:00:00Z", closes_at="2026-08-29T00:00:00Z"
        )
        assert ballot["effective_ballot_kind"] == "SUBCOMMITTEE", (
            "a revision-1 draft has no predecessor to inherit from, so the raised "
            "flag cannot force recirculation; got "
            f"{ballot['effective_ballot_kind']}"
        )
        assert ballot["eligible_voter_count"] == 3, (
            "a non-recirculation ballot polls the whole active voting roster, got "
            f"{ballot['eligible_voter_count']}"
        )
        a.assert_pct(ballot["required_approval_pct"], 50.1)
        a.assert_pct(ballot["required_return_rate_pct"], 50.0)


class TestVoteReturnAndAdjudicationDimensions:
    """A vote carries a return dimension and an adjudication dimension at once."""

    def test_position_changes_move_buckets_without_touching_the_return_count(self, api):
        """
        Supplying a different `position` takes the vote around a self-loop — it
        stays `CAST` — increments `position_change_count`, and moves the seat
        between position buckets without ever changing `returned_count`; a member
        may do this any number of times while the ballot is open.

        Design: Difficulty/non_linear_state_machine/vote_return_dimension_and_adjudication_dimension_evolve_independently
        """
        scenario = fx.voted_subcommittee_ballot(api)

        scenario.change_vote("v3", "ABSTAIN")
        after_first = scenario.get_ballot()
        a.assert_seat_ledger(
            after_first,
            affirmative=2,
            negative=0,
            abstain=1,
            returned=3,
            not_returned=0,
            eligible=3,
        )

        scenario.change_vote(
            "v3", "NEGATIVE", comment_text="Clause 12 torque ceiling is still unsafe"
        )
        vote = scenario.get_vote("v3")
        assert vote["status"] == "CAST", (
            f"a position change is a self-loop on CAST, got {vote['status']}"
        )
        assert vote["position"] == "NEGATIVE", (
            f"position expected NEGATIVE, got {vote['position']}"
        )
        assert vote["position_change_count"] == 2, (
            f"position_change_count expected 2, got {vote['position_change_count']}"
        )
        a.assert_seat_ledger(
            scenario.get_ballot(),
            affirmative=2,
            negative=1,
            abstain=0,
            returned=3,
            not_returned=0,
            eligible=3,
        )

    def test_voter_withdrawal_of_a_negative_leaves_the_return_dimension_cast(self, api):
        """
        `WITHDRAWN_BY_VOTER` moves `adjudication_status` to `WITHDRAWN_BY_VOTER` and
        rewrites `position` from `NEGATIVE` to `ABSTAIN`, so the objection leaves
        the approval base entirely.

        Design: Difficulty/non_linear_state_machine/vote_return_dimension_and_adjudication_dimension_evolve_independently
        """
        scenario = fx.voted_subcommittee_ballot(api)
        scenario.change_vote("v3", "ABSTAIN")
        scenario.change_vote(
            "v3", "NEGATIVE", comment_text="Clause 12 torque ceiling is still unsafe"
        )
        scenario.close_ballot()
        scenario.adjudicate(
            "v3",
            "WITHDRAWN_BY_VOTER",
            headers=scenario.member("p3"),
            adjudication_rationale="The fatigue annex answers the objection",
        )

        vote = scenario.get_vote("v3")
        assert vote["status"] == "CAST", (
            "a voter withdrawal at adjudication does not retract the return, got "
            f"{vote['status']}"
        )
        assert vote["adjudication_status"] == "WITHDRAWN_BY_VOTER", (
            f"adjudication_status expected WITHDRAWN_BY_VOTER, got {vote['adjudication_status']}"
        )
        assert vote["position"] == "ABSTAIN", (
            f"position expected ABSTAIN, got {vote['position']}"
        )
        assert vote["position_change_count"] == 2, (
            "the adjudication rewrite is not a voter position change, got "
            f"{vote['position_change_count']}"
        )

        ballot = scenario.get_ballot()
        a.assert_seat_ledger(
            ballot,
            affirmative=2,
            negative=0,
            abstain=1,
            returned=3,
            not_returned=0,
            eligible=3,
        )
        a.assert_pct(ballot["final_approval_pct"], 100.0)
        assert ballot["consensus_result"] == "APPROVED", (
            f"consensus_result expected APPROVED, got {ballot['consensus_result']}"
        )
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_READY", (
            "clearing the last pending negative with no persuasive ruling readies "
            "the draft for public review"
        )
