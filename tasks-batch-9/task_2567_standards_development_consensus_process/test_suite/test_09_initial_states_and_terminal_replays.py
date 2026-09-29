"""
Where each machine starts, and what happens when a caller tries to replay a
transition that has already been taken. Terminal states are refusals here, never
harmless no-ops, and a refused replay never rewrites the first outcome.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestDeclaredInitialStates:
    """A draft, a ballot and a vote all land on their declared initial states."""

    def test_draft_ballot_and_vote_open_on_their_initial_states(self, api):
        """
        The new ballot is created in `status` `OPEN` with `hold_reason` `NONE`,
        `closed_at` null, `consensus_result` `PENDING`, `affirmative_count`,
        `negative_count`, `abstain_count` and `returned_count` at 0,
        `not_returned_count` equal to `eligible_voter_count`, `return_rate_pct` 0.0, and
        both `provisional_approval_pct` and `final_approval_pct` null.

        Design: Corner/state_machines/initial_states_of_the_draft_ballot_and_vote_machines_are_drafting_open_and_cast
        """
        scenario = fx.work_item_in_development(api)
        draft = scenario.add_draft(total_clause_count=40, changed_clause_count=0)
        assert draft["status"] == "DRAFTING", (
            f"the draft machine starts at DRAFTING, got {draft['status']}"
        )

        ballot = scenario.open_ballot()
        assert ballot["status"] == "OPEN", (
            f"the ballot machine starts at OPEN, got {ballot['status']}"
        )
        assert ballot["consensus_result"] == "PENDING", (
            f"consensus_result starts at PENDING, got {ballot['consensus_result']}"
        )
        assert ballot["closed_at"] is None, (
            f"closed_at starts null, got {ballot['closed_at']}"
        )
        assert ballot["hold_reason"] == "NONE", (
            f"hold_reason starts at NONE, got {ballot['hold_reason']}"
        )
        assert ballot["eligible_voter_count"] == 3, (
            f"eligible_voter_count expected 3, got {ballot['eligible_voter_count']}"
        )

        scenario.cast("m2", "AFFIRMATIVE", vote_key="v2")
        after_first_return = scenario.get_ballot()
        assert after_first_return["not_returned_count"] == 2, (
            "two of the three seats are still outstanding, got "
            f"{after_first_return['not_returned_count']}"
        )

        vote = scenario.get_vote("v2")
        a.assert_has_fields(vote, "Vote")
        assert vote["status"] == "CAST", (
            f"the return dimension starts at CAST, got {vote['status']}"
        )
        assert vote["adjudication_status"] == "NOT_APPLICABLE", (
            "the adjudication dimension starts at NOT_APPLICABLE, got "
            f"{vote['adjudication_status']}"
        )
        assert vote["position_change_count"] == 0, (
            f"position_change_count starts at 0, got {vote['position_change_count']}"
        )
        assert vote["adjudicated_by_participant_id"] is None, (
            f"adjudicated_by_participant_id starts null, got {vote['adjudicated_by_participant_id']}"
        )


class TestTerminalStatesRefuseAReplay:
    """A terminal state has no outgoing edge, so the second call is an error."""

    def test_rejected_scope_can_never_be_approved(self, api):
        """
        A rejection requires a `rationale`, moves `progress_status` to the terminal
        `SCOPE_REJECTED`, and leaves both `sponsoring_committee_id` and `designation`
        null.

        Design: Corner/state_machines/scope_rejected_is_terminal_so_a_second_approve_scope_is_locked_out
        """
        scenario = fx.balanced_active_committee(api)
        scenario.propose_work_item("p1")
        rejected = validate_success(
            api.approve_scope(
                scenario.work_item_id,
                f.approve_scope_payload(
                    decision="REJECT",
                    designation=None,
                    rationale="The scope duplicates an existing standard",
                ),
                scenario.staff,
            ),
            200,
        )
        assert rejected["progress_status"] == "SCOPE_REJECTED", (
            f"progress_status expected SCOPE_REJECTED, got {rejected['progress_status']}"
        )

        response = api.approve_scope(
            scenario.work_item_id,
            f.approve_scope_payload(
                sponsoring_committee_id=scenario.committee_id, designation="STD-1400"
            ),
            scenario.staff,
        )
        validate_error(response, "ERR_INVALID_WORK_ITEM_STATE", 409)

        after = scenario.get_work_item()
        assert after["progress_status"] == "SCOPE_REJECTED", (
            f"the terminal state is unmoved, got {after['progress_status']}"
        )
        assert after["sponsoring_committee_id"] is None, (
            "a rejected scope never acquires a committee, got "
            f"{after['sponsoring_committee_id']}"
        )
        assert after["designation"] is None, (
            f"designation stays null, got {after['designation']}"
        )

    def test_closing_an_evaluated_ballot_is_refused(self, api):
        """
        Three preconditions apply: the ballot's `status` must be `OPEN`, else
        `ERR_BALLOT_NOT_OPEN`; the ballot's `hold_reason` must be `NONE`, since a ballot
        held because its committee fell out of balance or because an appeal is pending
        may not be closed, and the attempt is refused with `ERR_COMMITTEE_NOT_BALANCED`.

        Design: Corner/state_machines/closing_an_already_evaluated_ballot_returns_ballot_not_open
        """
        scenario = fx.draft_ready_for_public_review(api)
        before = scenario.get_ballot()
        assert before["status"] == "EVALUATED", (
            f"the ballot has already been closed and read, got {before['status']}"
        )

        response = api.close_ballot(scenario.ballot_id, scenario.chair)
        validate_error(response, "ERR_BALLOT_NOT_OPEN", 409)

        after = scenario.get_ballot()
        assert after["status"] == "EVALUATED", (
            f"the terminal state is unmoved, got {after['status']}"
        )
        assert after["consensus_result"] == "APPROVED", (
            f"consensus_result expected APPROVED, got {after['consensus_result']}"
        )
        a.assert_same_instant(after["closed_at"], "2026-08-01T00:00:00Z")
        a.assert_version_unchanged(before, after)
        assert scenario.get_draft()["status"] == "PUBLIC_REVIEW_READY", (
            "the draft keeps the state the first close gave it"
        )

    def test_adjudicating_an_affirmative_vote_is_refused(self, api):
        """
        The target vote must have `adjudication_status` `PENDING` and `status` `CAST`,
        else `ERR_VOTE_NOT_ADJUDICABLE`.

        Design: Corner/state_machines/adjudicating_an_affirmative_vote_returns_vote_not_adjudicable
        """
        scenario = fx.evaluated_ballot_with_pending_negative(api)
        affirmative = scenario.get_vote("v2")
        assert affirmative["adjudication_status"] == "NOT_APPLICABLE", (
            "an affirmative return never enters the adjudication dimension"
        )

        response = api.adjudicate_vote(
            affirmative["id"],
            f.adjudication_payload(
                resolution="NON_PERSUASIVE",
                adjudication_rationale="Attempting to adjudicate an affirmative return",
            ),
            scenario.chair,
        )
        validate_error(response, "ERR_VOTE_NOT_ADJUDICABLE", 409)

        after = scenario.get_vote("v2")
        assert after["adjudication_status"] == "NOT_APPLICABLE", (
            f"the vote is untouched, got {after['adjudication_status']}"
        )
        assert after["adjudicated_by_participant_id"] is None, (
            "no ruling was recorded, got "
            f"{after['adjudicated_by_participant_id']}"
        )
        assert scenario.get_vote("v3")["adjudication_status"] == "PENDING", (
            "the genuine pending negative is untouched"
        )
        ballot = scenario.get_ballot()
        assert ballot["final_approval_pct"] is None, (
            f"no final reading was taken, got {ballot['final_approval_pct']}"
        )
        assert ballot["consensus_result"] == "APPROVED_PENDING_NEGATIVES", (
            f"consensus_result expected APPROVED_PENDING_NEGATIVES, got {ballot['consensus_result']}"
        )
        assert scenario.get_draft()["status"] == "COMMENT_RESOLUTION", (
            "the draft still waits on the pending negative"
        )

    def test_disposing_an_already_rejected_comment_is_refused(self, api):
        """
        The first three each move an `OPEN` comment to the matching status and each
        require a non-empty `disposition_rationale`, which is recorded on the comment — a
        rejected comment in particular must carry a written reason, and omitting the
        rationale is `ERR_INVALID_REQUEST`. A comment already carrying a disposition is
        no longer `OPEN`, so a second disposition is refused with
        `ERR_INVALID_COMMENT_STATE`.

        Design: Corner/state_machines/disposing_an_already_rejected_comment_returns_invalid_comment_state
        """
        scenario = fx.work_item_with_draft(api)
        comment = scenario.submit_committee_comment(
            "p2",
            comment_type="TECHNICAL",
            comment_text="The torque band in clause 9 is too wide for cast fittings",
            clause_reference="9",
        )
        rejected = scenario.dispose_comment(
            comment["id"],
            disposition="REJECTED",
            disposition_rationale="Clause 9 already covers the band",
        )
        assert rejected["status"] == "REJECTED", (
            f"the first disposition landed, got {rejected['status']}"
        )

        response = api.dispose_comment(
            comment["id"],
            f.disposition_payload(
                disposition="REJECTED",
                disposition_rationale="Rejecting the same comment a second time",
            ),
            scenario.chair,
        )
        validate_error(response, "ERR_INVALID_COMMENT_STATE", 409)

        after = scenario.get_comment(comment["id"])
        assert after["status"] == "REJECTED", (
            f"the disposed comment is unmoved, got {after['status']}"
        )
        assert after["disposition_rationale"] == "Clause 9 already covers the band", (
            "the first rationale survives the refused overwrite, got "
            f"{after['disposition_rationale']}"
        )
        assert after["is_substantive"] is True, (
            f"a technical comment stays substantive, got {after['is_substantive']}"
        )
        a.assert_version_unchanged(rejected, after)

    def test_deciding_an_already_denied_appeal_is_refused(self, api):
        """
        `UPHELD` and `DENIED` are terminal; a further decision on either is refused with
        `ERR_INVALID_APPEAL_STATE`.

        Design: Corner/state_machines/deciding_an_already_denied_appeal_returns_invalid_appeal_state
        """
        scenario = fx.published_work_item(api)
        scenario.file_appeal(
            "p2",
            grounds="VOTING_PROCEDURE_DEFECT",
            statement="The ballot notice reached the roster late",
        )
        denied = scenario.decide_appeal(
            decision="DENY",
            decision_rationale="The notice period met the published minimum",
        )
        assert denied["status"] == "DENIED", (
            f"the first decision landed, got {denied['status']}"
        )

        response = api.decide_appeal(
            scenario.appeal_id,
            f.appeal_decision_payload(
                decision="ACCEPT_FOR_REVIEW",
                decision_rationale="Trying to reopen a denied appeal",
            ),
            scenario.appeals_board,
        )
        validate_error(response, "ERR_INVALID_APPEAL_STATE", 409)

        after = scenario.get_appeal()
        assert after["status"] == "DENIED", (
            f"the terminal decision is unmoved, got {after['status']}"
        )
        assert after["remedy"] == "NONE", (
            f"a denial grants no remedy, got {after['remedy']}"
        )
        a.assert_version_unchanged(denied, after)
        work_item = scenario.get_work_item()
        assert work_item["progress_status"] == "PUBLISHED", (
            f"the standard stays published, got {work_item['progress_status']}"
        )
        assert work_item["consensus_gate"] == "OPEN", (
            "the decided appeal no longer blocks the work item, got "
            f"{work_item['consensus_gate']}"
        )

    def test_resolving_an_already_declined_maintenance_item_is_refused(self, api):
        """
        The item must be in `RECEIVED`, else `ERR_INVALID_MAINTENANCE_STATE`; a resolved
        item cannot be re-resolved.

        Design: Corner/state_machines/resolving_an_already_declined_maintenance_item_returns_invalid_maintenance_state
        """
        scenario = fx.published_work_item(api)
        scenario.submit_maintenance_item(
            "p2",
            item_kind="INTERPRETATION_REQUEST",
            question_text="Does clause 12 apply to galvanised fittings?",
            clause_reference="12",
        )
        declined = scenario.resolve_maintenance(
            action="DECLINE",
            response_text="Out of scope for an interpretation",
        )
        assert declined["status"] == "DECLINED", (
            f"the first resolution landed, got {declined['status']}"
        )

        response = api.resolve_maintenance_item(
            scenario.maintenance_item_id,
            f.maintenance_resolution_payload(
                action="ISSUE_INTERPRETATION",
                response_text="Reversing the decline with an interpretation",
            ),
            scenario.chair,
        )
        validate_error(response, "ERR_INVALID_MAINTENANCE_STATE", 409)

        after = scenario.get_maintenance_item()
        assert after["status"] == "DECLINED", (
            f"the resolved item is unmoved, got {after['status']}"
        )
        assert after["response_text"] == "Out of scope for an interpretation", (
            f"the first response survives, got {after['response_text']}"
        )
        a.assert_version_unchanged(declined, after)
        work_item = scenario.get_work_item()
        assert work_item["interpretation_count"] == 0, (
            "the declined request issued no interpretation, got "
            f"{work_item['interpretation_count']}"
        )
        assert work_item["errata_count"] == 0, (
            f"errata_count is untouched, got {work_item['errata_count']}"
        )
