"""Board proposal lifecycle (revision loop, voting), quorum tally, and voter
eligibility / double-vote guards."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_member_payload, create_board_proposal_payload,
    setup_voting_proposal_with_board_member, cast_member_vote, make_member_headers,
    TEST_USERS,
)

BOARD = TEST_USERS["board_admin_headers"]
COOP = TEST_USERS["coop_admin_headers"]


class TestProposalRevisionCycle:
    """The DRAFT/UNDER_REVIEW revision loop, then OPEN_VOTING (PRD §3.6)."""

    def test_revision_loop_then_reaches_voting(self, api):
        """PRD §3.6: "Requesting revisions (`REQUEST_REVISIONS`) sends it from
        `UNDER_REVIEW` back to `DRAFT`, forming a revision loop. Opening voting
        (`OPEN_VOTING`) moves it from `UNDER_REVIEW` to `VOTING`". After a revision loop
        a second submit and open-voting reach VOTING.

        Design: Difficulty/non_linear_state_machine/nlsm_board_proposal_revision_cycle
        """
        proposal = get_success_data(api.create_board_proposal(
            create_board_proposal_payload(title="Bylaw A", proposal_type="BYLAW"), BOARD))
        api.advance_board_proposal(proposal["id"], {"action": "SUBMIT"}, BOARD)
        api.advance_board_proposal(proposal["id"], {"action": "REQUEST_REVISIONS"}, BOARD)
        api.advance_board_proposal(proposal["id"], {"action": "SUBMIT"}, BOARD)
        final = validate_success(
            api.advance_board_proposal(proposal["id"], {"action": "OPEN_VOTING"}, BOARD), 200)
        assert final["status"] == "VOTING"

    def test_request_revisions_returns_to_draft(self, api):
        """PRD §3.6: "Requesting revisions (`REQUEST_REVISIONS`) sends it from
        `UNDER_REVIEW` back to `DRAFT`, forming a revision loop."

        Design: Difficulty/non_linear_state_machine/nlsm_board_proposal_revision_cycle
        """
        proposal = get_success_data(api.create_board_proposal(
            create_board_proposal_payload(title="Bylaw A2", proposal_type="BYLAW"), BOARD))
        api.advance_board_proposal(proposal["id"], {"action": "SUBMIT"}, BOARD)
        revised = validate_success(
            api.advance_board_proposal(proposal["id"], {"action": "REQUEST_REVISIONS"}, BOARD), 200)
        assert revised["status"] == "DRAFT"


def test_quorum_met_single_board_member_approves(api):
    """PRD §3.6: "the quorum requirement, which is the eligible board-member count
    multiplied by one-half and rounded up to the next whole vote." PRD §3.6: "the
    outcome is `APPROVED` if the `for_count` is strictly greater than the
    `against_count`".

    Design: Corner/rbac/governance_quorum_approves_proposal
    """
    proposal, board_member = setup_voting_proposal_with_board_member(proposal_type="BUDGET")
    cast_member_vote(proposal["id"], board_member["id"], "FOR")
    tallied = validate_success(api.tally_board_proposal(proposal["id"], BOARD), 200)
    assert tallied["quorum_met"] is True
    assert tallied["status"] == "APPROVED"
    assert tallied["for_count"] == 1


def test_non_board_member_vote_rejected(api):
    """PRD §3.6: "the voter must be an `ACTIVE` board member (else
    `ERR_NOT_ELIGIBLE_VOTER`)".

    Design: Corner/rbac/non_board_member_vote_rejected_not_eligible
    """
    member = get_success_data(api.create_member(
        create_member_payload(full_name="Non B", email="nonb@x.com", is_board_member=False), COOP))
    proposal = get_success_data(api.create_board_proposal(
        create_board_proposal_payload(title="Policy P", proposal_type="POLICY"), BOARD))
    api.advance_board_proposal(proposal["id"], {"action": "SUBMIT"}, BOARD)
    api.advance_board_proposal(proposal["id"], {"action": "OPEN_VOTING"}, BOARD)
    res = api.cast_board_vote(
        proposal["id"], {"member_id": member["id"], "vote": "FOR"},
        make_member_headers(member["id"]))
    validate_error(res, "ERR_NOT_ELIGIBLE_VOTER", expected_status=409)


def test_duplicate_vote_rejected(api):
    """PRD §3.6: "the member must not have already voted on this proposal (else
    `ERR_ALREADY_VOTED`)".

    Design: Corner/rbac/duplicate_board_vote_rejected
    """
    proposal, board_member = setup_voting_proposal_with_board_member(proposal_type="BYLAW")
    cast_member_vote(proposal["id"], board_member["id"], "FOR")
    res = api.cast_board_vote(
        proposal["id"], {"member_id": board_member["id"], "vote": "AGAINST"},
        make_member_headers(board_member["id"]))
    validate_error(res, "ERR_ALREADY_VOTED", expected_status=409)
