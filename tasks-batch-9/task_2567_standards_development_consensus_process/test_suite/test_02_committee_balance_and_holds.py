"""
Committee balance on its two independent bases, the suspension cascade that a
loss of balance drives, and the close cascade that carries a single negative vote
all the way out to the work item's procedural gate.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestBalanceOnTwoBases:
    """The same roster is scored twice, over two different seat populations."""

    def test_suspended_producer_seats_leave_the_voting_basis_balanced(self, api):
        """
        The **voting basis** counts only seats whose `status` is `ACTIVE` and whose
        `voting_rights` is true; suspended seats, withdrawn seats, and active seats
        that are observers because `voting_rights` is false are excluded entirely.

        Design: Difficulty/dual_variant_calc/committee_balance_voting_basis_vs_roster_basis_divergence
        """
        scenario = fx.committee_with_extra_producer_seats(api, suspend_seats=("m4",))

        before = scenario.get_committee()
        a.assert_voting_balance(
            before,
            balance_status="BALANCED",
            active_member_count=4,
            distinct_category_count=3,
            dominance_pct=50.0,
        )

        scenario.patch_membership("m5", status="SUSPENDED")

        committee = scenario.get_committee()
        a.assert_voting_balance(
            committee,
            balance_status="BALANCED",
            active_member_count=3,
            distinct_category_count=3,
            dominance_pct=33.3,
            category_counts={"PRODUCER": 1, "USER": 1, "GENERAL_INTEREST": 1},
        )
        assert committee["status"] == "ACTIVE", (
            "the voting basis never left BALANCED, so no suspension cascade runs; "
            f"got {committee['status']}"
        )

    def test_suspended_producer_seats_still_dominate_the_roster_basis(self, api):
        """
        Three `ACTIVE` seats in three distinct categories, plus two `SUSPENDED` seats
        both in the `PRODUCER` category, gives a voting-basis dominance of 33.3
        percent with a `BALANCED` verdict, while the roster basis sees five seats
        with three of them `PRODUCER`, a dominance of 60.0 percent, a
        `distinct_category_count` of 3 and a `PROVISIONAL` verdict.

        Design: Difficulty/dual_variant_calc/committee_balance_voting_basis_vs_roster_basis_divergence
        """
        scenario = fx.committee_with_extra_producer_seats(api, suspend_seats=("m4",))
        scenario.patch_membership("m5", status="SUSPENDED")

        committee = scenario.get_committee()
        a.assert_roster_balance(
            committee,
            roster_balance_status="PROVISIONAL",
            roster_member_count=5,
            roster_dominance_pct=60.0,
        )
        a.assert_pct(committee["dominance_pct"], 33.3)
        assert committee["balance_status"] == "BALANCED", (
            "the two bases carry independent verdicts on identical data, got "
            f"{committee['balance_status']}"
        )
        assert committee["active_member_count"] == 3, (
            f"active_member_count expected 3, got {committee['active_member_count']}"
        )


class TestSuspendedCommitteeBlocksBallots:
    """A committee out of balance is suspended, and its work stops with it."""

    def test_ballot_is_refused_while_the_sponsoring_committee_is_suspended(self, api):
        """
        Before any of this, the sponsoring committee must be `ACTIVE` (else
        `ERR_COMMITTEE_NOT_ACTIVE`) and its voting-basis `balance_status` must be
        `BALANCED` (else `ERR_COMMITTEE_NOT_BALANCED`).

        Design: Difficulty/cross_entity_state_dependency/ballot_creation_blocked_while_sponsoring_committee_is_suspended
        """
        scenario = fx.suspended_committee_with_draft(api)

        committee = scenario.get_committee()
        assert committee["status"] == "SUSPENDED", (
            "dropping to two voting seats suspends the committee, got "
            f"{committee['status']}"
        )
        a.assert_voting_balance(
            committee,
            balance_status="UNBALANCED",
            active_member_count=2,
            distinct_category_count=2,
            dominance_pct=50.0,
        )
        a.assert_roster_balance(
            committee,
            roster_balance_status="BALANCED",
            roster_member_count=3,
            roster_dominance_pct=33.3,
        )
        assert scenario.get_work_item()["consensus_gate"] == "BLOCKED", (
            "the suspension gates every work item the committee sponsors"
        )

        draft_before = scenario.get_draft()
        response = api.create_ballot(
            f.ballot_payload(scenario.draft_id, scenario.committee_id),
            scenario.chair,
        )
        validate_error(response, "ERR_COMMITTEE_NOT_ACTIVE", 409)

        draft_after = scenario.get_draft()
        assert draft_after["status"] == "DRAFTING", (
            f"the refused ballot left the draft in DRAFTING, got {draft_after['status']}"
        )
        a.assert_version_unchanged(draft_before, draft_after)
        _, meta = validate_paginated(api.list_ballots(scenario.staff))
        a.assert_total_count(meta, 0)

    def test_restoring_the_seat_and_reactivating_lets_the_same_ballot_open(self, api):
        """
        A successful activation also re-derives the procedural gate of every work
        item this committee sponsors, and — when the committee was coming back from
        `SUSPENDED` — releases the procedural hold on its ballots, resetting every
        `hold_reason` of `COMMITTEE_UNBALANCED` back to `NONE`.

        Design: Difficulty/cross_entity_state_dependency/ballot_creation_blocked_while_sponsoring_committee_is_suspended
        """
        scenario = fx.suspended_committee_with_draft(api)
        validate_error(
            api.create_ballot(
                f.ballot_payload(scenario.draft_id, scenario.committee_id),
                scenario.chair,
            ),
            "ERR_COMMITTEE_NOT_ACTIVE",
            409,
        )

        scenario.patch_membership("m3", status="ACTIVE")
        scenario.activate_committee()

        committee = scenario.get_committee()
        assert committee["status"] == "ACTIVE", (
            f"the committee is restored, got {committee['status']}"
        )
        assert committee["balance_status"] == "BALANCED", (
            f"balance_status expected BALANCED, got {committee['balance_status']}"
        )
        assert scenario.get_work_item()["consensus_gate"] == "OPEN", (
            "the restored committee reopens its work items' gates"
        )

        ballot = scenario.open_ballot()
        assert ballot["status"] == "OPEN", (
            f"the identical request now succeeds, got {ballot['status']}"
        )
        assert ballot["eligible_voter_count"] == 3, (
            f"eligible_voter_count expected 3, got {ballot['eligible_voter_count']}"
        )
        assert ballot["hold_reason"] == "NONE", (
            f"hold_reason expected NONE, got {ballot['hold_reason']}"
        )
        assert scenario.get_draft()["status"] == "SUBCOMMITTEE_BALLOT", (
            "the draft moves into ballot on the successful creation"
        )


class TestCloseCascadeReachesTheWorkItem:
    """One negative vote, four hops: ballot, vote, draft, work item."""

    def test_close_freezes_the_ballot_and_makes_every_negative_pending(self, api):
        """
        **Hop two** moves every cast negative vote on the ballot from
        `adjudication_status` `NOT_APPLICABLE` to `PENDING`.

        Design: Difficulty/transitive_cascade/ballot_close_cascade_reaches_work_item_gate_through_vote_and_draft
        """
        scenario = fx.voted_subcommittee_ballot(api)
        before = scenario.get_ballot()
        assert scenario.get_vote("v3")["adjudication_status"] == "NOT_APPLICABLE", (
            "a negative starts outside the adjudication dimension"
        )

        scenario.close_ballot()

        ballot = scenario.get_ballot()
        assert ballot["status"] == "EVALUATED", (
            "the close evaluates in the same request, so CLOSED is never observable; "
            f"got {ballot['status']}"
        )
        a.assert_same_instant(ballot["closed_at"], "2026-08-01T00:00:00Z")
        assert ballot["consensus_result"] == "APPROVED_PENDING_NEGATIVES", (
            f"consensus_result expected APPROVED_PENDING_NEGATIVES, got {ballot['consensus_result']}"
        )
        assert ballot["pending_negative_count"] == 1, (
            f"pending_negative_count expected 1, got {ballot['pending_negative_count']}"
        )
        assert ballot["version"] > before["version"], (
            "the close advances the ballot's version"
        )
        assert scenario.get_vote("v3")["adjudication_status"] == "PENDING", (
            "the cast negative becomes pending on the close"
        )
        assert scenario.get_vote("v1")["adjudication_status"] == "NOT_APPLICABLE", (
            "an affirmative is never drawn into the adjudication dimension"
        )

    def test_close_carries_the_pending_negative_out_to_the_work_item_gate(self, api):
        """
        **Hop four** re-derives the parent work item's `consensus_gate` and
        `unresolved_negative_count`.

        Design: Difficulty/transitive_cascade/ballot_close_cascade_reaches_work_item_gate_through_vote_and_draft
        """
        scenario = fx.voted_subcommittee_ballot(api)
        draft_before = scenario.get_draft()
        work_item_before = scenario.get_work_item()

        scenario.close_ballot()

        draft = scenario.get_draft()
        assert draft["status"] == "COMMENT_RESOLUTION", (
            f"draft expected COMMENT_RESOLUTION, got {draft['status']}"
        )
        assert draft["unresolved_negative_count"] == 1, (
            f"draft unresolved_negative_count expected 1, got {draft['unresolved_negative_count']}"
        )
        assert draft["version"] > draft_before["version"], (
            "the close advances the draft's version"
        )

        work_item = scenario.get_work_item()
        assert work_item["consensus_gate"] == "BLOCKED", (
            f"consensus_gate expected BLOCKED, got {work_item['consensus_gate']}"
        )
        assert work_item["unresolved_negative_count"] == 1, (
            "the count reaches the work item through the draft, got "
            f"{work_item['unresolved_negative_count']}"
        )
        assert work_item["progress_status"] == "IN_DEVELOPMENT", (
            f"progress_status expected IN_DEVELOPMENT, got {work_item['progress_status']}"
        )
        assert work_item["version"] > work_item_before["version"], (
            "the close advances the work item's version"
        )
