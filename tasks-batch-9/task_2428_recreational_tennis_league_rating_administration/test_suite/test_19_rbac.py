"""Role gates, identity resolution, ownership and segregation of duties."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ACTOR_DISQUALIFIED,
    ERR_CHAIR_VOTED_ON_SUBJECT,
    ERR_MISSING_ROLE_HEADER,
    ERR_MISSING_USER_ID,
    ERR_NOT_SELF,
    ERR_NOT_TEAM_CAPTAIN,
    ERR_PLAYER_NOT_PLAYABLE,
    ERR_QUORUM_NOT_MET,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SELF_RATING_LOCKED,
    ERR_SOD_INTERESTED_PARTY,
    ERR_STALE_TEAM_VERSION,
    ERR_SUBJECT_NOT_UNDER_REVIEW,
    ERR_UNKNOWN_ROLE,
    ERR_VALIDATION,
)
from test_helpers.constants import (
    APPEAL_GRANTED,
    APPEAL_UNDER_REVIEW,
    APPEAL_UP,
    CLOCK_DEFAULT,
    INELIGIBLE_PLAYER_SUSPENDED,
    LEAGUE_DRAFT,
    OUTCOME_GRANT,
    PLAYER_ACTIVE,
    PLAYER_DISQUALIFIED,
    RATING_APPEAL_GRANTED,
    RATING_COMPUTER_RATED,
    RATING_SELF_RATED,
    RATING_SOURCE_SELF,
    RATING_UNRATED,
    SPOT_INELIGIBLE,
    SPOT_PENDING,
    STRIKE_SCORECARD_FALSIFICATION,
    TIER_SECTION,
    VOTE_SUPPORT,
)
from test_helpers.fixtures import Scenario
from test_helpers.test_users import (
    LEAGUE_COORDINATOR,
    SECTION_ADMIN,
    headers_without_user_id,
    make_captain_headers,
    make_committee_chair_headers,
    make_committee_member_headers,
    make_player_headers,
    make_role_headers,
)


def _appeal_under_review(api):
    """ph1's own UP appeal is open for ballots; pc1 and pc2 are disinterested."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section()
    s.add_player("ph1", level=3.5, full_name="Adam Ace")
    s.add_committee()
    appeal = get_success_data(
        api.create_rating_appeal(
            f.appeal_payload(s.player_id("ph1"), APPEAL_UP, 4.0),
            make_player_headers(s.player_id("ph1")),
        ),
        201,
    )
    get_success_data(api.start_appeal_review(appeal["id"], s.chair_headers()))
    return s, appeal


def test_the_appellant_cannot_vote_on_its_own_appeal_even_wearing_the_role(api):
    """The role header is genuine; the identity behind it is the interested party.

    PRD 3.8: "Interested parties are barred outright, with
    `ERR_SOD_INTERESTED_PARTY`: a member may not vote on a rating appeal whose
    `player_id` is the member itself, and may not vote on a grievance whose
    `filed_by_captain_player_id` is the member, whose `remedy_target_player_id` is
    the member, or whose `against_team_id` is a team the member captains."

    Design: Corner/rbac/committee_member_voting_on_its_own_appeal_returns_403_sod_interested_party
    """
    s, appeal = _appeal_under_review(api)
    ballot = f.vote_payload(appeal["id"], VOTE_SUPPORT, note="I support my own appeal.")

    response = api.create_committee_vote(
        ballot, make_committee_member_headers(s.player_id("ph1"))
    )
    validate_error(response, ERR_SOD_INTERESTED_PARTY, 403)
    reported = response.json()["data"]["error_id"]
    # CommitteeMember is the role this endpoint requires.
    assert reported != ERR_ROLE_NOT_PERMITTED
    # And the subject is UNDER_REVIEW, so the state gate passed.
    assert reported != ERR_SUBJECT_NOT_UNDER_REVIEW

    untouched = get_success_data(api.get_rating_appeal(appeal["id"], SECTION_ADMIN))
    assert untouched["support_vote_count"] == 0
    assert untouched["oppose_vote_count"] == 0

    _votes, meta = validate_paginated(
        api.list_player_committee_votes(s.player_id("ph1"), SECTION_ADMIN)
    )
    assert meta["total_count"] == 0

    # Only the interested identity was barred.
    cast = get_success_data(
        api.create_committee_vote(ballot, s.member_headers("pc1")), 201
    )
    assert cast["voter_player_id"] == s.player_id("pc1")


def test_a_chair_that_voted_on_the_appeal_may_not_also_decide_it(api):
    """Ballot and verdict must come from two people, keyed on the voter identity.

    PRD 3.8: "The chair must not have cast a vote on this subject, failing which the
    refusal is `ERR_CHAIR_VOTED_ON_SUBJECT`."

    Design: Corner/rbac/chair_deciding_an_appeal_it_voted_on_returns_403_chair_voted_on_subject
    """
    s, appeal = _appeal_under_review(api)
    get_success_data(
        api.create_committee_vote(
            f.vote_payload(appeal["id"], VOTE_SUPPORT), s.member_headers("pc1")
        ),
        201,
    )
    get_success_data(
        api.create_committee_vote(
            f.vote_payload(appeal["id"], VOTE_SUPPORT, note="Chair also supports."),
            make_committee_member_headers(s.player_id("pch")),
        ),
        201,
    )

    response = api.decide_appeal(
        appeal["id"],
        {
            "outcome": OUTCOME_GRANT,
            "decision_note": "Granting on the committee's recommendation.",
        },
        s.chair_headers(),
    )
    validate_error(response, ERR_CHAIR_VOTED_ON_SUBJECT, 403)
    # The quorum is satisfied at two supporting against none opposed.
    assert response.json()["data"]["error_id"] != ERR_QUORUM_NOT_MET

    stalled = get_success_data(api.get_rating_appeal(appeal["id"], SECTION_ADMIN))
    assert stalled["status"] == APPEAL_UNDER_REVIEW
    assert stalled["support_vote_count"] == 2
    assert stalled["decided_by_chair_player_id"] is None
    assert stalled["granted_level"] is None

    appellant = s.refresh_player("ph1")
    assert appellant["rating_level"] == 3.5
    assert appellant["rating_type"] == RATING_COMPUTER_RATED

    # A chair who cast no ballot may pronounce the very same verdict.
    granted = get_success_data(
        api.decide_appeal(
            appeal["id"],
            {
                "outcome": OUTCOME_GRANT,
                "decision_note": "Granting on the committee's recommendation.",
            },
            s.chair_headers("pc2"),
        )
    )
    assert granted["status"] == APPEAL_GRANTED
    assert granted["granted_level"] == 4.0
    assert granted["decided_by_chair_player_id"] == s.player_id("pc2")
    assert s.refresh_player("ph1")["rating_type"] == RATING_APPEAL_GRANTED


# ---------------------------------------------------------------------------
def test_a_player_cannot_create_a_league_however_wellformed_the_payload(api):
    """The role gate answers before the body is ever inspected.

    PRD 2.1: "If the role is recognised but the endpoint being called does not list
    it among its authorised roles, the request is refused with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/player_creating_a_league_returns_403_role_not_permitted
    """
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section()
    s.add_player("ph1", full_name="Adam Ace")
    payload = f.league_payload(
        s.section["id"],
        ntrp_level=3.5,
        registration_closes_at="2026-12-01T00:00:00Z",
        roster_lock_at="2026-12-01T00:00:00Z",
        season_end_at="2026-12-31T00:00:00Z",
    )

    response = api.create_league(payload, make_player_headers(s.player_id("ph1")))
    validate_error(response, ERR_ROLE_NOT_PERMITTED, 403)
    reported = response.json()["data"]["error_id"]
    # Player is one of the six declared roles, and the payload is well formed.
    assert reported != ERR_UNKNOWN_ROLE
    assert reported != ERR_VALIDATION

    _leagues, meta = validate_paginated(
        api.list_leagues(
            SECTION_ADMIN, {"section_id": s.section["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0

    created = get_success_data(api.create_league(payload, SECTION_ADMIN), 201)
    assert created["tier"] == TIER_SECTION
    assert created["status"] == LEAGUE_DRAFT


def test_an_entity_backed_role_needs_an_identifier_that_resolves(api):
    """Absent and unresolvable identifiers both fail on the same code.

    PRD 2.1: "A missing or unresolvable identifier under one of those four roles is
    refused with `ERR_MISSING_USER_ID` (HTTP 401)."

    Design: Corner/rbac/captain_write_without_a_user_id_returns_401_missing_user_id
    """
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section()
    s.create_facility()
    s.create_league(tier=TIER_SECTION)
    s.open_registration()
    s.add_player("ph1", level=4.0, full_name="Adam Ace")
    payload = f.team_payload(
        s.league["id"], s.facility["id"], name="Headerless Hitters"
    )

    response = api.create_team(payload, headers_without_user_id("Captain"))
    validate_error(response, ERR_MISSING_USER_ID, 401)
    reported = response.json()["data"]["error_id"]
    # The role header is present and valid, and no identity exists to compare yet.
    assert reported != ERR_MISSING_ROLE_HEADER
    assert reported != ERR_NOT_TEAM_CAPTAIN

    validate_error(
        api.create_team(payload, make_role_headers("Captain", NON_EXISTENT_UUID)),
        ERR_MISSING_USER_ID,
        401,
    )

    _teams, meta = validate_paginated(
        api.list_teams(
            SECTION_ADMIN, {"league_id": s.league["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0

    created = get_success_data(
        api.create_team(payload, make_role_headers("Captain", s.player_id("ph1"))), 201
    )
    assert created["captain_player_id"] == s.player_id("ph1")
    assert created["name"] == "Headerless Hitters"


# ---------------------------------------------------------------------------
def _one_rated_and_one_unrated_player(api):
    """pa1 is COMPUTER_RATED at 3.5; pa2 is still UNRATED and self-ratable."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section()
    s.add_player("pa1", level=3.5, full_name="Adam Ace")
    s.add_player("pa2", full_name="Bea Backhand")
    return s


def test_a_player_role_actor_may_rate_only_the_record_it_owns(api):
    """The endpoint admits the Player role, but only over that player's own row.

    PRD 2.1: "A `Player`-role actor addressing a player record other than its own is
    refused with `ERR_NOT_SELF` (HTTP 403) - this guards the self-rating operation
    and the filing of a rating appeal."

    Design: Corner/rbac/player_rating_another_player_returns_403_not_self
    """
    s = _one_rated_and_one_unrated_player(api)
    target = s.player_id("pa2")
    declaration = f.rating_payload(3.0, RATING_SOURCE_SELF)

    response = api.assign_rating(
        target, declaration, make_player_headers(s.player_id("pa1"))
    )
    validate_error(response, ERR_NOT_SELF, 403)
    reported = response.json()["data"]["error_id"]
    # Player is one of the two roles this endpoint lists.
    assert reported != ERR_ROLE_NOT_PERMITTED
    # And the target is UNRATED, so a self-rating on it is still admissible.
    assert reported != ERR_SELF_RATING_LOCKED

    untouched = get_success_data(api.get_player(target, SECTION_ADMIN))
    assert untouched["rating_type"] == RATING_UNRATED
    assert untouched["rating_level"] is None
    assert untouched["self_rated_level"] is None

    owned = get_success_data(
        api.assign_rating(target, declaration, make_player_headers(target))
    )
    assert owned["rating_type"] == RATING_SELF_RATED
    assert owned["self_rated_level"] == 3.0
    assert owned["rating_level"] == 3.0

    # The ownership scope binds the Player role alone.
    overwritten = get_success_data(
        api.assign_rating(target, f.rating_payload(3.0), LEAGUE_COORDINATOR)
    )
    assert overwritten["rating_type"] == RATING_COMPUTER_RATED
    assert overwritten["self_rated_level"] == 3.0


# ---------------------------------------------------------------------------
def _two_draft_teams_under_different_captains(api):
    """Two empty DRAFT teams in one open league, captained by pa1 and pb1."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section()
    s.create_facility()
    s.create_league(tier=TIER_SECTION, ntrp_level=4.0, min_active_roster_size=2)
    s.open_registration()
    for key, name in (
        ("pa1", "Adam Ace"),
        ("pa2", "Bea Backhand"),
        ("pb1", "Cal Crosscourt"),
        ("pb2", "Dot Dropshot"),
    ):
        s.add_player(key, level=4.0, full_name=name)
    s.create_team("ta", "pa1", "Ace Attack")
    s.create_team("tb", "pb1", "Baseline Bandits")
    return s


def test_a_captain_may_not_stage_a_roster_spot_on_a_peers_team(api):
    """Two holders of the same role, disjoint resources: ownership, not permission.

    PRD 2.1: "A `Captain`-role actor addressing a team it does not captain, or a
    match neither of whose sides it captains, is refused with
    `ERR_NOT_TEAM_CAPTAIN` (HTTP 403) - this guards roster-spot creation, roster-spot
    activation, roster-spot removal, team registration, team withdrawal, match
    confirmation, scorecard submission, scorecard review, scorecard amendment,
    grievance filing and grievance withdrawal."

    Design: Corner/rbac/captain_adding_a_spot_to_another_captains_team_returns_403_not_team_captain
    """
    s = _two_draft_teams_under_different_captains(api)
    target_team = s.teams["tb"]["id"]
    live_version = s.team_version("tb")
    payload = f.roster_spot_payload(target_team, s.player_id("pb2"), live_version)

    response = api.create_roster_spot(
        payload, make_role_headers("Captain", s.player_id("pa1"))
    )
    validate_error(response, ERR_NOT_TEAM_CAPTAIN, 403)
    reported = response.json()["data"]["error_id"]
    # The declared version is the target team's live one.
    assert reported != ERR_STALE_TEAM_VERSION
    # And Captain is the only role this endpoint accepts.
    assert reported != ERR_ROLE_NOT_PERMITTED

    _spots, meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN, {"team_id": target_team, "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0
    assert s.team_version("tb") == live_version

    staged = get_success_data(
        api.create_roster_spot(
            payload, make_role_headers("Captain", s.player_id("pb1"))
        ),
        201,
    )
    assert staged["status"] == SPOT_PENDING
    assert staged["team_id"] == target_team


# ---------------------------------------------------------------------------
def _team_whose_captain_has_been_disqualified(api):
    """Two weight-3 findings take pa1 to a ledger of 6, past both limits."""
    s = _two_draft_teams_under_different_captains(api)
    s.add_spot("ta", "pa1")
    s.activate_spot("ta", "pa1")
    for reason in ("First falsification finding", "Second falsification finding"):
        get_success_data(
            api.create_strike(
                f.strike_payload(
                    s.player_id("pa1"), STRIKE_SCORECARD_FALSIFICATION, reason=reason
                ),
                LEAGUE_COORDINATOR,
            ),
            201,
        )
    return s


def test_a_disqualified_captain_keeps_the_captaincy_but_loses_every_write(api):
    """Actor status is examined ahead of ownership and of every business rule.

    PRD 2.1: "A further gate applies to writes: an entity-backed actor whose own
    `Player` row is in status `DISQUALIFIED` may not perform any write operation, and
    is refused with `ERR_ACTOR_DISQUALIFIED` (HTTP 403)."

    Design: Corner/rbac/disqualified_captain_write_returns_403_actor_disqualified
    """
    s = _team_whose_captain_has_been_disqualified(api)
    team_id = s.teams["ta"]["id"]
    version_before = s.team_version("ta")

    response = api.create_roster_spot(
        f.roster_spot_payload(team_id, s.player_id("pa2"), version_before),
        make_role_headers("Captain", s.player_id("pa1")),
    )
    validate_error(response, ERR_ACTOR_DISQUALIFIED, 403)
    reported = response.json()["data"]["error_id"]
    # The disqualified actor is still the team's captain_player_id.
    assert reported != ERR_NOT_TEAM_CAPTAIN
    # And the player being added is ACTIVE; that code guards the target, not the actor.
    assert reported != ERR_PLAYER_NOT_PLAYABLE

    actor = get_success_data(api.get_player(s.player_id("pa1"), SECTION_ADMIN))
    assert actor["status"] == PLAYER_DISQUALIFIED
    assert actor["strike_count"] == 6

    spots, meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN, {"team_id": team_id, "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert spots[0]["status"] == SPOT_INELIGIBLE
    assert spots[0]["ineligible_reason"] == INELIGIBLE_PLAYER_SUSPENDED

    team = get_success_data(api.get_team(team_id, SECTION_ADMIN))
    assert team["version"] == version_before
    assert team["active_roster_size"] == 0

    # The bar covers writes only.
    readable = get_success_data(
        api.get_team(team_id, make_role_headers("Captain", s.player_id("pa1")))
    )
    assert readable["captain_player_id"] == s.player_id("pa1")


# ---------------------------------------------------------------------------
def test_every_role_may_read_one_player_while_the_listing_omits_the_player_role(api):
    """The same entity is gated three different ways, and all three must hold.

    PRD 2.1: "If the role is recognised but the endpoint being called does not list
    it among its authorised roles, the request is refused with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/single_player_read_is_shared_by_all_six_roles_while_the_collection_is_not
    """
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section()
    s.add_player("pa1", full_name="Adam Ace")
    player_id = s.player_id("pa1")

    every_role = (
        make_committee_member_headers(player_id),
        SECTION_ADMIN,
        LEAGUE_COORDINATOR,
        make_captain_headers(player_id),
        make_player_headers(player_id),
        make_committee_chair_headers(player_id),
    )
    for headers in every_role:
        one = get_success_data(api.get_player(player_id, headers))
        assert one["id"] == player_id
        assert one["full_name"] == "Adam Ace"
        assert one["rating_type"] == RATING_UNRATED
        assert one["status"] == PLAYER_ACTIVE

    validate_error(
        api.list_players(
            make_player_headers(player_id), {"limit": 100, "offset": 0}
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    _listed, meta = validate_paginated(
        api.list_players(LEAGUE_COORDINATOR, {"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1

    enrolment = f.player_payload(s.section["id"], "Bea Backhand")
    validate_error(
        api.create_player(enrolment, make_captain_headers(player_id)),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    enrolled = get_success_data(
        api.create_player(enrolment, LEAGUE_COORDINATOR), 201
    )
    assert enrolled["section_id"] == s.section["id"]
