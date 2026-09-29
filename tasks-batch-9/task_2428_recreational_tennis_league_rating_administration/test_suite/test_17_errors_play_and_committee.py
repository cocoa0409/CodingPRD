"""Lineup, appeal, vote and rating-epoch refusals."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_APPEAL_ALREADY_OPEN,
    ERR_AUTO_GRANT_MUST_BE_GRANTED,
    ERR_CHAIR_VOTED_ON_SUBJECT,
    ERR_INELIGIBLE_LINEUP,
    ERR_INVALID_RATING_LEVEL,
    ERR_QUORUM_NOT_MET,
    ERR_RATING_PERIOD_CLOSED,
    ERR_RECALC_PHASE_INVALID,
    ERR_SCORECARD_LINE_INVALID,
    ERR_SELF_RATING_LOCKED,
    ERR_SOD_INTERESTED_PARTY,
    ERR_SUBJECT_NOT_UNDER_REVIEW,
    ERR_SUBJECT_TYPE_MISMATCH,
)
from test_helpers.constants import (
    APPEAL_DENIED,
    APPEAL_DOWN,
    APPEAL_GRANTED,
    APPEAL_SUBMITTED,
    APPEAL_UNDER_REVIEW,
    APPEAL_UP,
    CLOCK_DEFAULT,
    OUTCOME_DENY,
    OUTCOME_GRANT,
    RATING_APPEAL_GRANTED,
    RATING_COMPUTER_RATED,
    RATING_PERIOD_RECALC_IN_PROGRESS,
    RATING_PERIOD_RECALC_PUBLISHED,
    RESULT_PENDING,
    SCORECARD_SUBMITTED,
    SUBJECT_RATING_APPEAL,
    VOTE_SUPPORT,
)
from test_helpers.fixtures import (
    Scenario,
    played_match,
    six_a_side_league,
    standard_three_lines,
)
from test_helpers.test_users import (
    LEAGUE_COORDINATOR,
    SECTION_ADMIN,
    make_player_headers,
)


def _played_match_awaiting_its_card(api):
    """M1 is PLAYED and PENDING with six ACTIVE spots on each side."""
    s = six_a_side_league(api)
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.confirm_match("m1")
    s.set_clock("2026-08-15T21:00:00Z")
    s.mark_played("m1")
    return s


def test_a_player_may_not_be_fielded_on_two_lines_of_one_match(api):
    """Every named player holds an ACTIVE spot, yet the captain plays twice.

    PRD 3.6: "Every player identifier on a line must hold a roster spot at `status`
    `ACTIVE` on the team that fields that side of that line, and no player may
    appear on two lines of the same match; a violation of either is refused with
    `ERR_INELIGIBLE_LINEUP`."

    Design: Corner/errors/player_named_on_two_lines_of_one_match_returns_422_ineligible_lineup
    """
    s = _played_match_awaiting_its_card(api)
    version_before = s.matches["m1"]["version"]
    canonical = standard_three_lines(s)
    doubled = [
        canonical[0],
        f.scorecard_line(
            2,
            [s.player_id("ph1"), s.player_id("ph4")],
            [s.player_id("pa3"), s.player_id("pa4")],
            [f.set_score(6, 0), f.set_score(6, 0)],
        ),
        canonical[2],
    ]

    response = api.create_scorecard(
        f.scorecard_payload(s.matches["m1"]["id"], doubled),
        s.captain_headers("th"),
    )
    validate_error(response, ERR_INELIGIBLE_LINEUP, 422)
    # Every line still names two distinct identifiers per side.
    assert response.json()["data"]["error_id"] != ERR_SCORECARD_LINE_INVALID

    _cards, meta = validate_paginated(
        api.list_scorecards(
            SECTION_ADMIN,
            {"match_id": s.matches["m1"]["id"], "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 0

    match = s.refresh_match("m1")
    assert match["result_status"] == RESULT_PENDING
    assert match["version"] == version_before

    # The spot must belong to the side that fields the line, too.
    wrong_side = [
        canonical[0],
        f.scorecard_line(
            2,
            [s.player_id("pa1"), s.player_id("ph4")],
            [s.player_id("pa3"), s.player_id("pa4")],
            [f.set_score(6, 0), f.set_score(6, 0)],
        ),
        canonical[2],
    ]
    validate_error(
        api.create_scorecard(
            f.scorecard_payload(s.matches["m1"]["id"], wrong_side),
            s.captain_headers("th"),
        ),
        ERR_INELIGIBLE_LINEUP,
        422,
    )

    accepted = get_success_data(
        api.create_scorecard(
            f.scorecard_payload(s.matches["m1"]["id"], canonical),
            s.captain_headers("th"),
        ),
        201,
    )
    assert accepted["status"] == SCORECARD_SUBMITTED


# ---------------------------------------------------------------------------
def _one_rated_player_and_a_committee(api):
    """A COMPUTER_RATED player at 3.5 plus a chair and two members, no leagues."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section()
    s.add_player("ph1", level=3.5, full_name="Hank Halfvolley")
    s.add_committee()
    return s


def _open_up_appeal(s, api):
    return get_success_data(
        api.create_rating_appeal(
            f.appeal_payload(s.player_id("ph1"), APPEAL_UP, 4.0),
            make_player_headers(s.player_id("ph1")),
        ),
        201,
    )


def test_an_open_upward_appeal_blocks_a_downward_one_from_the_same_player(api):
    """The one-open-appeal rule is scoped to the player and not to the direction.

    PRD 3.8: "A player may hold at most one appeal at a time in the `SUBMITTED` or
    `UNDER_REVIEW` states, and a second filing is refused with
    `ERR_APPEAL_ALREADY_OPEN`."

    Design: Corner/errors/second_appeal_while_the_first_is_open_returns_409_appeal_already_open
    """
    s = _one_rated_player_and_a_committee(api)
    first = _open_up_appeal(s, api)
    assert first["status"] == APPEAL_SUBMITTED

    down_payload = f.appeal_payload(
        s.player_id("ph1"),
        APPEAL_DOWN,
        3.0,
        reason="On reflection the level is too high.",
    )
    response = api.create_rating_appeal(
        down_payload, make_player_headers(s.player_id("ph1"))
    )
    validate_error(response, ERR_APPEAL_ALREADY_OPEN, 409)
    # 3.0 is a legal half-step inside the 2.5 to 5.0 lattice.
    assert response.json()["data"]["error_id"] != ERR_INVALID_RATING_LEVEL

    filed, meta = validate_paginated(
        api.list_rating_appeals(
            SECTION_ADMIN,
            {"player_id": s.player_id("ph1"), "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert filed[0]["direction"] == APPEAL_UP
    assert filed[0]["requested_level"] == 4.0

    get_success_data(api.start_appeal_review(first["id"], s.chair_headers()))
    denied = get_success_data(
        api.decide_appeal(
            first["id"],
            {"outcome": OUTCOME_DENY, "decision_note": "Not persuaded"},
            s.chair_headers(),
        )
    )
    assert denied["status"] == APPEAL_DENIED

    # DENIED is neither SUBMITTED nor UNDER_REVIEW, so the slot is free again.
    second = get_success_data(
        api.create_rating_appeal(
            down_payload, make_player_headers(s.player_id("ph1"))
        ),
        201,
    )
    assert second["direction"] == APPEAL_DOWN
    assert second["status"] == APPEAL_SUBMITTED


def test_a_ballot_cast_before_the_chair_opens_the_review_is_refused(api):
    """The subject resolves and the voter is disinterested; only the state is wrong.

    PRD 3.8: "The subject must be `UNDER_REVIEW`, failing which the refusal is
    `ERR_SUBJECT_NOT_UNDER_REVIEW`."

    Design: Corner/errors/vote_on_a_submitted_appeal_returns_409_subject_not_under_review
    """
    s = _one_rated_player_and_a_committee(api)
    appeal = _open_up_appeal(s, api)
    ballot = f.vote_payload(
        appeal["id"], VOTE_SUPPORT, note="Dynamic rating supports the move."
    )

    response = api.create_committee_vote(ballot, s.member_headers("pc1"))
    validate_error(response, ERR_SUBJECT_NOT_UNDER_REVIEW, 409)
    reported = response.json()["data"]["error_id"]
    # The member is neither the appellant nor a party to the appeal.
    assert reported != ERR_SOD_INTERESTED_PARTY
    # And the identifier does resolve inside RatingAppeal.
    assert reported != ERR_SUBJECT_TYPE_MISMATCH

    stored = get_success_data(api.get_rating_appeal(appeal["id"], SECTION_ADMIN))
    assert stored["status"] == APPEAL_SUBMITTED
    assert stored["support_vote_count"] == 0
    assert stored["oppose_vote_count"] == 0

    _votes, meta = validate_paginated(
        api.list_player_committee_votes(s.player_id("pc1"), s.member_headers("pc1"))
    )
    assert meta["total_count"] == 0

    get_success_data(api.start_appeal_review(appeal["id"], s.chair_headers()))
    cast = get_success_data(
        api.create_committee_vote(ballot, s.member_headers("pc1")), 201
    )
    assert cast["vote"] == VOTE_SUPPORT
    assert cast["subject_type"] == SUBJECT_RATING_APPEAL
    assert cast["voter_player_id"] == s.player_id("pc1")

    reopened = get_success_data(api.get_rating_appeal(appeal["id"], SECTION_ADMIN))
    assert reopened["status"] == APPEAL_UNDER_REVIEW
    assert reopened["support_vote_count"] == 1


# ---------------------------------------------------------------------------
def _appeal_under_review_with_no_votes(api):
    """The appellant never played a line, so auto-grant was pinned false."""
    s = _one_rated_player_and_a_committee(api)
    appeal = _open_up_appeal(s, api)
    get_success_data(api.start_appeal_review(appeal["id"], s.chair_headers()))
    return s, appeal


def test_a_grant_without_votes_or_auto_grant_eligibility_is_refused(api):
    """Neither gateway to GRANT is open, and the DENY branch is unaffected.

    PRD 3.8: "Also on the grant branch, either `auto_grant_eligible` must be true,
    or the committee must have delivered a quorum - `support_vote_count` at least 2
    *and* strictly greater than `oppose_vote_count`; failing both, the refusal is
    `ERR_QUORUM_NOT_MET`."

    Design: Corner/errors/granting_an_appeal_with_no_votes_returns_422_quorum_not_met
    """
    s, appeal = _appeal_under_review_with_no_votes(api)
    response = api.decide_appeal(
        appeal["id"],
        {"outcome": OUTCOME_GRANT, "decision_note": "Chair is persuaded on the merits."},
        s.chair_headers(),
    )
    validate_error(response, ERR_QUORUM_NOT_MET, 422)
    reported = response.json()["data"]["error_id"]
    # auto_grant_eligible is false here, and the chair cast no ballot.
    assert reported != ERR_AUTO_GRANT_MUST_BE_GRANTED
    assert reported != ERR_CHAIR_VOTED_ON_SUBJECT

    stored = get_success_data(api.get_rating_appeal(appeal["id"], SECTION_ADMIN))
    assert stored["status"] == APPEAL_UNDER_REVIEW
    assert stored["granted_level"] is None
    assert stored["decided_at"] is None
    assert stored["auto_grant_eligible"] is False

    appellant = s.refresh_player("ph1")
    assert appellant["rating_level"] == 3.5
    assert appellant["rating_type"] == RATING_COMPUTER_RATED

    # The quorum guards only the grant path.
    denied = get_success_data(
        api.decide_appeal(
            appeal["id"],
            {"outcome": OUTCOME_DENY, "decision_note": "Insufficient support"},
            s.chair_headers(),
        )
    )
    assert denied["status"] == APPEAL_DENIED


def test_two_supporting_ballots_open_the_grant_path_for_the_same_appeal(api):
    """The identical decide call succeeds once the quorum exists.

    PRD 3.8: "Casting a vote recomputes the subject's `support_vote_count` (its
    votes of `SUPPORT`) and `oppose_vote_count` (its votes of `OPPOSE`) and
    increases the subject's `version` by 1; an `ABSTAIN` counts toward neither
    tally, though it is recorded and it does consume the member's one vote."

    Design: Corner/errors/granting_an_appeal_with_no_votes_returns_422_quorum_not_met
    """
    s, appeal = _appeal_under_review_with_no_votes(api)
    for member_key in ("pc1", "pc2"):
        get_success_data(
            api.create_committee_vote(
                f.vote_payload(appeal["id"], VOTE_SUPPORT),
                s.member_headers(member_key),
            ),
            201,
        )

    with_quorum = get_success_data(api.get_rating_appeal(appeal["id"], SECTION_ADMIN))
    assert with_quorum["support_vote_count"] == 2
    assert with_quorum["oppose_vote_count"] == 0
    assert with_quorum["auto_grant_eligible"] is False

    granted = get_success_data(
        api.decide_appeal(
            appeal["id"],
            {"outcome": OUTCOME_GRANT, "decision_note": "Committee supports the move."},
            s.chair_headers(),
        )
    )
    assert granted["status"] == APPEAL_GRANTED
    assert granted["granted_level"] == 4.0
    assert granted["decided_by_chair_player_id"] == s.player_id("pch")

    appellant = s.refresh_player("ph1")
    assert appellant["rating_level"] == 4.0
    assert appellant["rating_type"] == RATING_APPEAL_GRANTED


# ---------------------------------------------------------------------------
def _section_latched_in_recalc(api):
    """One verified match, then phase 1 of the year-end recalculation."""
    s = six_a_side_league(api)
    played_match(s, standard_three_lines(s), match_key="m1")
    get_success_data(api.year_end_recalc(s.section["id"], SECTION_ADMIN))
    return s


def test_even_a_coordinator_rating_write_is_refused_once_recalc_has_begun(api):
    """The latch is on the section's epoch, not on the actor or the rating source.

    PRD 2.2: "Once the section leaves `OPEN_SEASON` - in either of the two later
    postures - the rating period is closed, and five operations are refused with
    `ERR_RATING_PERIOD_CLOSED` (HTTP 409): assigning a rating to a player, adding a
    roster spot, activating a roster spot, a captain removing a roster spot, and
    granting a rating appeal."

    Design: Corner/errors/coordinator_rating_write_during_recalc_returns_409_rating_period_closed
    """
    s = _section_latched_in_recalc(api)
    player_id = s.player_id("ph3")

    response = api.assign_rating(
        player_id, f.rating_payload(4.5), LEAGUE_COORDINATOR
    )
    validate_error(response, ERR_RATING_PERIOD_CLOSED, 409)
    reported = response.json()["data"]["error_id"]
    # The actor is a coordinator writing a COMPUTER rating.
    assert reported != ERR_SELF_RATING_LOCKED
    # And that code guards the two recalculation endpoints only.
    assert reported != ERR_RECALC_PHASE_INVALID

    untouched = s.refresh_player("ph3")
    assert untouched["rating_level"] == 4.0
    assert untouched["rating_type"] == RATING_COMPUTER_RATED
    assert untouched["proposed_recalc_level"] == 4.0

    section = get_success_data(api.get_section(s.section["id"], SECTION_ADMIN))
    assert section["rating_period_status"] == RATING_PERIOD_RECALC_IN_PROGRESS
    assert section["recalc_run_index"] == 0
    assert section["recalculated_player_count"] == 12

    # RECALC_PUBLISHED closes the period just as firmly; there is no reopening.
    get_success_data(api.publish_recalc(s.section["id"], SECTION_ADMIN))
    validate_error(
        api.assign_rating(player_id, f.rating_payload(4.5), LEAGUE_COORDINATOR),
        ERR_RATING_PERIOD_CLOSED,
        409,
    )
    published = get_success_data(api.get_section(s.section["id"], SECTION_ADMIN))
    assert published["rating_period_status"] == RATING_PERIOD_RECALC_PUBLISHED
