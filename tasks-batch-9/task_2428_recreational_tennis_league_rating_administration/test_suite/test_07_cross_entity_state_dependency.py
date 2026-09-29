"""Rejections sourced entirely from a second, untouched entity."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals
from test_helpers.api_errors import (
    ERR_ADVANCEMENT_SLOTS_EXHAUSTED,
    ERR_RATING_PERIOD_CLOSED,
    ERR_TEAM_ROSTER_NONCOMPLIANT,
)
from test_helpers.constants import (
    AGE_18_OVER,
    APPEAL_UNDER_REVIEW,
    APPEAL_UP,
    FORMAT_MENS_DOUBLES,
    INELIGIBLE_PLAYER_SUSPENDED,
    LEAGUE_PLAYOFFS,
    LEAGUE_REGISTRATION_OPEN,
    OUTCOME_GRANT,
    PLAYER_STRIKE_SUSPENDED,
    RATING_COMPUTER_RATED,
    RATING_PERIOD_RECALC_IN_PROGRESS,
    RESULT_FINALIZED,
    RESULT_PENDING,
    SCHED_DEFAULTED,
    SCHED_SCHEDULED,
    SIDE_HOME,
    SPOT_ACTIVE,
    SPOT_INELIGIBLE,
    STRIKE_SCORECARD_FALSIFICATION,
    SUBJECT_RATING_APPEAL,
    TEAM_IN_PLAY,
    TIER_DISTRICT,
    TIER_LOCAL,
    TIER_SECTION,
    VOTE_SUPPORT,
)
from test_helpers.fixtures import Scenario, two_team_league
from test_helpers.test_users import (
    LEAGUE_COORDINATOR,
    SECTION_ADMIN,
    make_player_headers,
)


# ---------------------------------------------------------------------------
# Instance: match_confirm_blocked_by_opposing_team_compliance_flag_rejected
# ---------------------------------------------------------------------------
def _scheduled_match_with_suspended_away_player(api):
    s = two_team_league(
        api,
        roster_size=2,
        section_kwargs={
            "min_matches_for_playoff_eligibility": 1,
            "strike_limit": 3,
            "disqualification_strike_limit": 6,
        },
    )
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    strike = get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("pa2"),
                STRIKE_SCORECARD_FALSIFICATION,
                reason="Fabricated a line score",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    return s, strike


def test_confirm_refused_because_the_away_team_lost_roster_compliance(api):
    """A match whose own schedule state admits confirm is still refused.

    PRD 3.5: "Both teams must have `roster_compliant` true, failing which the
    refusal is `ERR_TEAM_ROSTER_NONCOMPLIANT` - this is the check that strands a
    team whose roster has fallen below its league's `min_active_roster_size`,
    whether through removals or through a cascade of ineligibility."

    Design: Difficulty/cross_entity_state_dependency/match_confirm_blocked_by_opposing_team_compliance_flag_rejected
    """
    s, _ = _scheduled_match_with_suspended_away_player(api)

    response = api.confirm_match(s.matches["m1"]["id"], s.captain_headers("th"))
    validate_error(response, ERR_TEAM_ROSTER_NONCOMPLIANT, 409)

    match = s.refresh_match("m1")
    assert match["schedule_status"] == SCHED_SCHEDULED
    assert_instant_equals(match["scheduled_start_at"], "2026-08-15T18:00:00Z")
    assert match["result_status"] == RESULT_PENDING


def test_confirm_rejection_leaves_the_strike_cascade_as_the_only_state_change(api):
    """The blocking state lives on the away Team, not on the Match.

    PRD 3.5: "Both teams must have `roster_compliant` true, failing which the
    refusal is `ERR_TEAM_ROSTER_NONCOMPLIANT`"

    Design: Difficulty/cross_entity_state_dependency/match_confirm_blocked_by_opposing_team_compliance_flag_rejected
    """
    s, strike = _scheduled_match_with_suspended_away_player(api)

    validate_error(
        api.confirm_match(s.matches["m1"]["id"], s.captain_headers("th")),
        ERR_TEAM_ROSTER_NONCOMPLIANT,
        409,
    )

    away = s.refresh_team("ta")
    home = s.refresh_team("th")
    assert away["status"] == TEAM_IN_PLAY
    assert away["roster_compliant"] is False
    assert away["active_roster_size"] == 1
    assert home["status"] == TEAM_IN_PLAY
    assert home["roster_compliant"] is True
    assert home["active_roster_size"] == 2
    assert s.refresh_league()["noncompliant_team_count"] == 1

    spot = s.refresh_spot("pa2")
    assert spot["status"] == SPOT_INELIGIBLE
    assert spot["ineligible_reason"] == INELIGIBLE_PLAYER_SUSPENDED
    assert spot["source_strike_id"] == strike["id"]

    player = s.refresh_player("pa2")
    assert player["status"] == PLAYER_STRIKE_SUSPENDED
    assert player["strike_count"] == 3


# ---------------------------------------------------------------------------
# Instance: appeal_grant_blocked_by_section_rating_epoch_rejected
# ---------------------------------------------------------------------------
def _appeal_with_quorum_and_closed_epoch(api):
    s = two_team_league(api, roster_size=2, ntrp_level=3.5, with_committee=True)
    appeal = get_success_data(
        api.create_rating_appeal(
            f.appeal_payload(
                s.player_id("ph2"),
                APPEAL_UP,
                4.0,
                reason="Consistently competitive against 4.0 opposition in practice sets",
            ),
            make_player_headers(s.player_id("ph2")),
        ),
        201,
    )
    get_success_data(api.start_appeal_review(appeal["id"], s.chair_headers()))
    for member in ("pc1", "pc2"):
        get_success_data(
            api.create_committee_vote(
                f.vote_payload(appeal["id"], VOTE_SUPPORT, SUBJECT_RATING_APPEAL),
                s.member_headers(member),
            ),
            201,
        )
    get_success_data(api.year_end_recalc(s.section["id"], SECTION_ADMIN))
    return s, appeal


def test_appeal_grant_refused_while_the_section_sits_in_recalc(api):
    """Quorum is met and the chair never voted, yet the grant is refused.

    PRD 3.8: "On the grant branch the section must be at `OPEN_SEASON`, failing
    which the refusal is `ERR_RATING_PERIOD_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/appeal_grant_blocked_by_section_rating_epoch_rejected
    """
    s, appeal = _appeal_with_quorum_and_closed_epoch(api)

    response = api.decide_appeal(
        appeal["id"],
        {"outcome": OUTCOME_GRANT, "decision_note": "Quorum reached 2-0"},
        s.chair_headers(),
    )
    validate_error(response, ERR_RATING_PERIOD_CLOSED, 409)

    stored = get_success_data(api.get_rating_appeal(appeal["id"], SECTION_ADMIN))
    assert stored["status"] == APPEAL_UNDER_REVIEW
    assert stored["granted_level"] is None
    assert stored["decided_by_chair_player_id"] is None
    assert stored["support_vote_count"] == 2
    assert stored["oppose_vote_count"] == 0
    assert stored["auto_grant_eligible"] is False


def test_appeal_grant_rejection_writes_no_rating_and_no_roster_cascade(api):
    """The refused grant must not touch the appellant's rating or roster spot.

    PRD 2.8: "five operations are refused with `ERR_RATING_PERIOD_CLOSED` (HTTP
    409): assigning a rating to a player, adding a roster spot, activating a
    roster spot, a captain removing a roster spot, and granting a rating appeal."

    Design: Difficulty/cross_entity_state_dependency/appeal_grant_blocked_by_section_rating_epoch_rejected
    """
    s, appeal = _appeal_with_quorum_and_closed_epoch(api)

    validate_error(
        api.decide_appeal(
            appeal["id"],
            {"outcome": OUTCOME_GRANT, "decision_note": "Quorum reached 2-0"},
            s.chair_headers(),
        ),
        ERR_RATING_PERIOD_CLOSED,
        409,
    )

    section = get_success_data(api.get_section(s.section["id"], SECTION_ADMIN))
    assert section["rating_period_status"] == RATING_PERIOD_RECALC_IN_PROGRESS
    assert section["recalculated_player_count"] == 0

    player = s.refresh_player("ph2")
    assert player["rating_level"] == 3.5
    assert player["rating_type"] == RATING_COMPUTER_RATED

    spot = s.refresh_spot("ph2")
    assert spot["status"] == SPOT_ACTIVE
    assert spot["ineligible_reason"] is None

    team = s.refresh_team("th")
    assert team["active_roster_size"] == 2
    assert team["roster_compliant"] is True
    assert s.refresh_league()["noncompliant_team_count"] == 0


# ---------------------------------------------------------------------------
# Instance: advance_teams_blocked_by_parent_league_capacity_rejected
# ---------------------------------------------------------------------------
def _full_parent_ladder(api):
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.create_section(min_matches_for_playoff_eligibility=1)
    s.create_facility(court_count=4)
    ladder_common = {
        "ntrp_level": 4.0,
        "age_group": AGE_18_OVER,
        "format": FORMAT_MENS_DOUBLES,
        "min_active_roster_size": 2,
    }
    lgs = s.create_league(tier=TIER_SECTION, **ladder_common)
    lgd = s.create_league(
        tier=TIER_DISTRICT, parent_league_id=lgs["id"], max_teams=1, **ladder_common
    )
    s.open_registration(lgd)
    lgl = s.create_league(
        tier=TIER_LOCAL,
        parent_league_id=lgd["id"],
        min_playoff_eligible_players=0,
        advancement_slots=1,
        **ladder_common,
    )
    s.open_registration(lgl)

    for key in ("pd1", "pd2", "ph1", "ph2", "pa1", "pa2"):
        s.add_player(key, level=4.0)

    s.create_team("td", "pd1", "District Incumbents", league=lgd)
    s.fill_roster("td", ["pd1", "pd2"])
    s.register_team("td")

    s.create_team("th", "ph1", "Balboa Aces", league=lgl)
    s.fill_roster("th", ["ph1", "ph2"])
    s.create_team("ta", "pa1", "Volley Kings", league=lgl)
    s.fill_roster("ta", ["pa1", "pa2"])
    s.register_team("th")
    s.register_team("ta")

    s.set_clock("2026-08-08T00:00:00Z")
    s.lock_rosters(lgl)
    s.start_play(lgl)

    s.create_match("m1", "th", "ta", league=lgl)
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.set_clock("2026-08-15T18:00:00Z")
    s.default_match("m1", SIDE_HOME, "NO_SHOW")
    get_success_data(api.seed_playoffs(lgl["id"], LEAGUE_COORDINATOR))
    return s, lgs, lgd, lgl


def test_advance_teams_refused_when_the_parent_league_is_already_full(api):
    """The promoter is a valid PLAYOFFS league; only the parent's capacity blocks.

    PRD 3.9: "And the parent must have room: the parent's
    `registered_team_count` plus the number of teams about to be promoted must
    not exceed the parent's `max_teams`, failing which the refusal is
    `ERR_ADVANCEMENT_SLOTS_EXHAUSTED`."

    Design: Difficulty/cross_entity_state_dependency/advance_teams_blocked_by_parent_league_capacity_rejected
    """
    s, _lgs, _lgd, lgl = _full_parent_ladder(api)

    response = api.advance_teams(lgl["id"], LEAGUE_COORDINATOR)
    validate_error(response, ERR_ADVANCEMENT_SLOTS_EXHAUSTED, 409)

    stored = s.refresh_league(lgl["id"])
    assert stored["status"] == LEAGUE_PLAYOFFS
    assert stored["seeded_team_count"] == 2
    assert stored["finalized_match_count"] == 1

    away = s.refresh_team("ta")
    home = s.refresh_team("th")
    assert away["playoff_seed"] == 1 and away["status"] == TEAM_IN_PLAY
    assert home["playoff_seed"] == 2 and home["status"] == TEAM_IN_PLAY


def test_advance_teams_rejection_promotes_nothing_into_the_parent_tier(api):
    """No half-written promotion: the parent keeps exactly its one team.

    PRD 3.9: "And the parent must have room: the parent's
    `registered_team_count` plus the number of teams about to be promoted must
    not exceed the parent's `max_teams`"

    Design: Difficulty/cross_entity_state_dependency/advance_teams_blocked_by_parent_league_capacity_rejected
    """
    s, _lgs, lgd, lgl = _full_parent_ladder(api)

    validate_error(
        api.advance_teams(lgl["id"], LEAGUE_COORDINATOR),
        ERR_ADVANCEMENT_SLOTS_EXHAUSTED,
        409,
    )

    parent = s.refresh_league(lgd["id"])
    assert parent["status"] == LEAGUE_REGISTRATION_OPEN
    assert parent["registered_team_count"] == 1

    rows, _meta = validate_paginated(api.list_teams(SECTION_ADMIN, {"limit": 100}))
    in_parent = [t for t in rows if t["league_id"] == lgd["id"]]
    assert len(in_parent) == 1
    assert in_parent[0]["id"] == s.teams["td"]["id"]
    assert [t for t in rows if t.get("advanced_from_team_id")] == []

    match = s.refresh_match("m1")
    assert match["schedule_status"] == SCHED_DEFAULTED
    assert match["result_status"] == RESULT_FINALIZED
    away = s.refresh_team("ta")
    assert away["matches_won"] == 1
    assert away["lines_won"] == 3
    assert away["standings_points"] == 6
    home = s.refresh_team("th")
    assert home["matches_lost"] == 1
    assert home["standings_points"] == 0
