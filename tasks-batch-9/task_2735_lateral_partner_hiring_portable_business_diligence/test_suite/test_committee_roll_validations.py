"""Committee integrity validations: the declared roll is a hard ceiling and one voter
gets exactly one live ballot per round."""

from test_helpers import (
    ApiErrorId,
    MEMBER_1_USER_ID,
    MEMBER_2_USER_ID,
    MEMBER_3_USER_ID,
    PEER_CHAIR_USER_ID,
    TEST_USERS,
    api_client,
    cast_vote,
    cast_vote_payload,
    make_committee_member_headers,
    read_offer,
    setup_offer_in_committee_review,
    validate_error,
    validate_success,
)

CHAIR = TEST_USERS["committee_chair_headers"]


def test_the_roll_is_a_ceiling_so_a_fourth_ballot_on_a_three_voter_roll_is_refused():
    """The acting user must not be the candidate's `sponsor_user_id`
    (`ERR_SPONSOR_CANNOT_VOTE`), must not already hold an `ACTIVE` vote on this offer
    (`ERR_DUPLICATE_VOTE`), and the offer's `active_vote_count` must be strictly below its
    `eligible_voter_count` (`ERR_VOTE_ROLL_FULL`).

    Design: Corner/validations/vote_roll_full_rejects_a_fourth_ballot
    """
    ctx = setup_offer_in_committee_review("SLIM", eligible_voter_count=3)
    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_3_USER_ID, "APPROVE")

    full = read_offer(ctx["offer"]["id"])
    assert full["active_vote_count"] == 3
    assert full["eligible_voter_count"] == 3

    fourth = api_client.cast_vote(
        ctx["offer"]["id"],
        cast_vote_payload(decision="APPROVE", round_number=1),
        make_committee_member_headers(PEER_CHAIR_USER_ID),
    )
    validate_error(fourth, ApiErrorId.ERR_VOTE_ROLL_FULL.value)

    offer = read_offer(ctx["offer"]["id"])
    assert offer["active_vote_count"] == 3
    assert offer["votes_cast_total"] == 3
    assert offer["eligible_voter_count"] == 3
    assert offer["round_number"] == 1
    assert offer["status"] == "COMMITTEE_REVIEW"


def test_a_voter_cannot_replace_a_live_ballot_by_casting_a_second_one():
    """Casting a vote records `voter_user_id` from `X-User-ID`, lands the vote with `status`
    `ACTIVE`, increments both `votes_cast_total` and `active_vote_count` by 1, and increments
    the offer's `version` by 1.
    The acting user must not be the candidate's `sponsor_user_id`
    (`ERR_SPONSOR_CANNOT_VOTE`), must not already hold an `ACTIVE` vote on this offer
    (`ERR_DUPLICATE_VOTE`), and the offer's `active_vote_count` must be strictly below its
    `eligible_voter_count` (`ERR_VOTE_ROLL_FULL`).

    Design: Corner/validations/second_ballot_from_the_same_voter_is_rejected
    """
    ctx = setup_offer_in_committee_review("SLIM", eligible_voter_count=3)
    first = cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    assert first["voter_user_id"] == MEMBER_1_USER_ID

    second = api_client.cast_vote(
        ctx["offer"]["id"],
        cast_vote_payload(
            decision="REJECT",
            round_number=1,
            rationale="On reflection I want to change my vote.",
        ),
        make_committee_member_headers(MEMBER_1_USER_ID),
    )
    validate_error(second, ApiErrorId.ERR_DUPLICATE_VOTE.value)

    kept = validate_success(api_client.get_vote(first["id"], CHAIR))
    assert kept["decision"] == "APPROVE"
    assert kept["status"] == "ACTIVE"

    offer = read_offer(ctx["offer"]["id"])
    assert offer["active_vote_count"] == 1
    assert offer["votes_cast_total"] == 1
    assert offer["status"] == "COMMITTEE_REVIEW"
