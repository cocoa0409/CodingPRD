"""Tallying a ballot: two denominators, and the ballot-array guards."""
from test_helpers import (
    ApiErrorId,
    fixtures,
    get_success_data,
    make_council_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import ballot


def _abstention_ballots(world):
    members = world["members"]
    return [
        ballot(members["chair"]["id"], "YES"),
        ballot(members["industry_two"]["id"], "YES"),
        ballot(members["local"]["id"], "YES"),
        ballot(members["fire"]["id"], "NO"),
        ballot(members["public"]["id"], "NO"),
        ballot(members["design"]["id"], "ABSTAIN"),
    ]


def test_01_quorum_counts_seats_while_the_supermajority_counts_decisive_ballots(api):
    """"Quorum is measured against *seats*: `voting_seats_at_call` is the
    committee's `active_voting_member_count` at the moment of the call", and "the
    vote record's own `quorum_required` is two thirds of `voting_seats_at_call`,
    rounded up to the next whole member". "The supermajority, by contrast, is
    measured against *ballots cast for or against*: the decisive total is
    `yes_count` plus `no_count`, with abstentions excluded, even though
    abstentions did count toward quorum." Three YES against two NO with one
    abstention clears 60 percent of five decisive ballots.

    Design: Difficulty/combinatorial_formula/vote_tally_two_denominators_with_abstention
    """
    world = fixtures.setup_convened_hearing(api)

    response = fixtures.record_vote(api, world, ballots=_abstention_ballots(world))
    vote = validate_success(response, 201)

    assert vote["voting_seats_at_call"] == 6
    assert vote["quorum_required"] == 4
    assert vote["yes_count"] == 3
    assert vote["no_count"] == 2
    assert vote["abstain_count"] == 1
    assert vote["outcome"] == "APPROVED"
    assert vote["outcome_reason"] == "MAJORITY_APPROVED"


def test_02_absent_count_is_seats_less_the_cast_total(api):
    """"`absent_count` is `voting_seats_at_call` less that cast total", so six
    ballots against six seats leave nobody absent, and the approving outcome
    still "advances the proposal `COMMENT_CLOSED` → `APPROVED`" with the final
    ratio recomputed at the vote.

    Design: Difficulty/combinatorial_formula/vote_tally_two_denominators_with_abstention
    """
    world = fixtures.setup_convened_hearing(api)

    vote = get_success_data(
        fixtures.record_vote(api, world, ballots=_abstention_ballots(world)), 201
    )
    assert vote["absent_count"] == 0
    assert vote["final_benefit_cost_ratio_at_vote"] == 1.01

    proposal = get_success_data(
        api.get_amendment_proposal(world["proposal_id"], make_council_admin_headers())
    )
    assert proposal["review_status"] == "APPROVED"


def _foreign_member_world(api):
    """The convened ENERGY hearing plus one member of a second committee who is
    named twice on the ballot array."""
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.add_mechanical_committee(api, world, seated=("chair",))
    return fixtures.setup_convened_hearing(api, world=world)


def _foreign_member_ballots(world):
    members = world["members"]
    foreign_id = world["mechanical_members"]["chair"]["id"]
    return [
        ballot(members["chair"]["id"], "YES"),
        ballot(members["industry_two"]["id"], "YES"),
        ballot(members["local"]["id"], "YES"),
        ballot(members["design"]["id"], "YES"),
        ballot(members["fire"]["id"], "NO"),
        ballot(foreign_id, "NO"),
        ballot(foreign_id, "NO"),
    ]


def test_03_foreign_ballot_member_outranks_the_duplicate_ballot_check(api):
    """"Every `member_id` must be an `ACTIVE` voting member of the hearing's
    committee, or `ERR_BALLOT_MEMBER_NOT_ON_COMMITTEE`; no `member_id` may appear
    twice in one `ballots` array, or `ERR_DUPLICATE_BALLOT`". A single array that
    breaks both rules is answered by the referential failure, which the priority
    ladder places above the constraint failure.

    Design: Difficulty/priority_pair_validation_conflict/ballot_member_not_on_committee_outranks_duplicate_ballot
    """
    world = _foreign_member_world(api)

    response = fixtures.record_vote(
        api, world, ballots=_foreign_member_ballots(world)
    )
    error = validate_error(
        response, ApiErrorId.ERR_BALLOT_MEMBER_NOT_ON_COMMITTEE, 409
    )
    assert error["error_id"] != ApiErrorId.ERR_DUPLICATE_BALLOT


def test_04_a_refused_ballot_array_leaves_the_hearing_convened_and_empty(api):
    """The chair "records one immutable **vote record** per agenda item", so a
    refused array writes nothing: the hearing stays `CONVENED` after its
    `SCHEDULED` → `CONVENED` move, and the proposal stays at `COMMENT_CLOSED`.

    Design: Difficulty/priority_pair_validation_conflict/ballot_member_not_on_committee_outranks_duplicate_ballot
    """
    world = _foreign_member_world(api)

    fixtures.record_vote(api, world, ballots=_foreign_member_ballots(world))

    hearing = get_success_data(
        api.get_hearing(world["hearing_id"], make_council_admin_headers())
    )
    assert hearing["status"] == "CONVENED"

    _, meta = validate_paginated(
        api.list_hearing_votes(world["hearing_id"], make_council_admin_headers())
    )
    assert meta["total_count"] == 0

    proposal = get_success_data(
        api.get_amendment_proposal(world["proposal_id"], make_council_admin_headers())
    )
    assert proposal["review_status"] == "COMMENT_CLOSED"
