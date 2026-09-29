"""Start of play, the two match dimensions, verification and compensation."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals
from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_MATCH_NOT_YET_PLAYABLE,
    ERR_MATCH_RESULT_STATE_INVALID,
    ERR_SCORECARD_STATE_FORBIDS_ACTION,
)
from test_helpers.constants import (
    INELIGIBLE_PLAYER_SUSPENDED,
    LEAGUE_IN_PLAY,
    PLAYER_ACTIVE,
    PLAYER_STRIKE_SUSPENDED,
    RESULT_PENDING,
    RESULT_VERIFIED,
    SCHED_CONFIRMED,
    SCHED_PLAYED,
    SCORECARD_VERIFIED,
    SPOT_ACTIVE,
    SPOT_INELIGIBLE,
    STRIKE_ACTIVE,
    STRIKE_RESCINDED,
    STRIKE_SCORECARD_FALSIFICATION,
    TEAM_IN_PLAY,
    TEAM_ROSTER_LOCKED,
)
from test_helpers.fixtures import six_a_side_league, two_team_league
from test_helpers.test_users import LEAGUE_COORDINATOR, SECTION_ADMIN

RESCIND_REASON = "Falsification finding overturned; the disputed card was mis-attributed"


def _three_locked_teams_one_of_them_suspended(api):
    """Three teams locked while compliant; then team C's second player is suspended."""
    s = two_team_league(
        api,
        roster_size=2,
        start=False,
        with_committee=True,
        section_kwargs={
            "min_matches_for_playoff_eligibility": 1,
            "strike_limit": 3,
            "disqualification_strike_limit": 6,
        },
    )
    s.add_player("p3a", level=4.0, full_name="Cal Cross")
    s.add_player("p3b", level=4.0, full_name="Dan Drop")
    s.create_team("tc", "p3a", "Court Crashers")
    s.fill_roster("tc", ["p3a", "p3b"])
    s.register_team("tc")

    s.set_clock("2026-08-08T00:00:00Z")
    s.lock_rosters()
    strike = get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("p3b"),
                STRIKE_SCORECARD_FALSIFICATION,
                reason="Fabricated set scores on a submitted card",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    return s, strike


def test_start_play_promotes_the_compliant_teams_and_strands_the_third(api):
    """Two compliant teams satisfy the quota while the third stays where it is.

    PRD 3.4: "The cascade is *conditional*: every team at `ROSTER_LOCKED` whose
    `roster_compliant` is true transitions to `IN_PLAY`, and every team at
    `ROSTER_LOCKED` whose `roster_compliant` is false stays exactly where it is,
    remaining at `ROSTER_LOCKED` and remaining inside `noncompliant_team_count`."

    Design: Corner/state_machines/start_play_promotes_only_compliant_teams_and_strands_the_suspended_one
    """
    s, strike = _three_locked_teams_one_of_them_suspended(api)
    started = get_success_data(api.start_play(s.league["id"], LEAGUE_COORDINATOR))
    assert started["status"] == LEAGUE_IN_PLAY
    assert started["registered_team_count"] == 3
    assert started["noncompliant_team_count"] == 1

    assert s.refresh_team("th")["status"] == TEAM_IN_PLAY
    assert s.refresh_team("ta")["status"] == TEAM_IN_PLAY

    stranded = s.refresh_team("tc")
    assert stranded["status"] == TEAM_ROSTER_LOCKED
    assert stranded["active_roster_size"] == 1
    assert stranded["roster_compliant"] is False

    charged = s.refresh_player("p3b")
    assert charged["status"] == PLAYER_STRIKE_SUSPENDED
    assert charged["strike_count"] == 3

    spot = s.refresh_spot("p3b")
    assert spot["status"] == SPOT_INELIGIBLE
    assert spot["ineligible_reason"] == INELIGIBLE_PLAYER_SUSPENDED
    assert spot["source_strike_id"] == strike["id"]
    assert s.refresh_spot("p3a")["status"] == SPOT_ACTIVE


def test_rescinding_the_only_strike_restores_the_spot_but_not_the_team_status(api):
    """Compensation is exact at player, spot, team and league level, and stops there.

    PRD 3.7: "The roster restoration is deliberately **surgical**: only those roster
    spots at `INELIGIBLE` whose `ineligible_reason` is `PLAYER_SUSPENDED` *and*
    whose `source_strike_id` names the strike just rescinded return to `ACTIVE`, and
    on doing so both `ineligible_reason` and `source_strike_id` are cleared to null."

    Design: Corner/state_machines/strike_rescind_reverses_every_suspension_side_effect_without_repromoting_the_team
    """
    s, strike = _three_locked_teams_one_of_them_suspended(api)
    s.start_play()

    rescinded = get_success_data(
        api.rescind_strike(
            strike["id"], {"rescinded_reason": RESCIND_REASON}, s.chair_headers()
        )
    )
    assert rescinded["status"] == STRIKE_RESCINDED
    assert rescinded["rescinded_reason"] == RESCIND_REASON
    assert rescinded["weight"] == 3

    restored_player = s.refresh_player("p3b")
    assert restored_player["status"] == PLAYER_ACTIVE
    assert restored_player["strike_count"] == 0

    spot = s.refresh_spot("p3b")
    assert spot["status"] == SPOT_ACTIVE
    assert spot["ineligible_reason"] is None
    assert spot["source_strike_id"] is None

    team = s.refresh_team("tc")
    assert team["status"] == TEAM_ROSTER_LOCKED
    assert team["active_roster_size"] == 2
    assert team["roster_compliant"] is True

    league = s.refresh_league()
    assert league["status"] == LEAGUE_IN_PLAY
    assert league["noncompliant_team_count"] == 0

    _active, active_meta = validate_paginated(
        api.list_strikes(
            SECTION_ADMIN,
            {
                "player_id": s.player_id("p3b"),
                "status": STRIKE_ACTIVE,
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert active_meta["total_count"] == 0

    _all, all_meta = validate_paginated(
        api.list_strikes(
            SECTION_ADMIN,
            {"player_id": s.player_id("p3b"), "limit": 100, "offset": 0},
        )
    )
    assert all_meta["total_count"] == 1


def _confirmed_match_one_minute_short_of_its_end(api):
    """M1 runs 18:00 to 21:00 and the clock reads 20:59."""
    s = six_a_side_league(api)
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.confirm_match("m1")
    s.set_clock("2026-08-15T20:59:00Z")
    return s


def test_marking_played_before_the_scheduled_end_is_premature(api):
    """179 of 180 minutes is not enough; the gate is the end instant, not the start.

    PRD 3.6: "The only additional requirement is temporal: the current instant must
    have reached `scheduled_end_at`. Marking a match played before its scheduled end
    is refused with `ERR_MATCH_NOT_YET_PLAYABLE`"

    Design: Corner/state_machines/mark_played_one_minute_before_scheduled_end_returns_match_not_yet_playable
    """
    s = _confirmed_match_one_minute_short_of_its_end(api)
    response = api.mark_played(s.matches["m1"]["id"], LEAGUE_COORDINATOR)
    validate_error(response, ERR_MATCH_NOT_YET_PLAYABLE, 422)
    assert response.json()["response_type"] == "error"
    assert response.json()["data"]["error_id"] != ERR_INVALID_STATE

    match = s.refresh_match("m1")
    assert match["schedule_status"] == SCHED_CONFIRMED
    assert match["result_status"] == RESULT_PENDING


def test_marking_played_moves_the_schedule_dimension_only(api):
    """At exactly the end instant the schedule advances and the result stays PENDING.

    PRD 3.6: "**Marking a match played** is the coordinator's act, taking it from
    `CONFIRMED` to `PLAYED`, and it is what opens the scorecard submission window."

    Design: Corner/state_machines/mark_played_moves_schedule_dimension_only_and_leaves_result_dimension_pending
    """
    s = _confirmed_match_one_minute_short_of_its_end(api)
    s.set_clock("2026-08-15T21:00:00Z")
    played = get_success_data(
        api.mark_played(s.matches["m1"]["id"], LEAGUE_COORDINATOR)
    )
    assert played["schedule_status"] == SCHED_PLAYED
    assert played["result_status"] == RESULT_PENDING
    assert played["verified_at"] is None
    assert played["winner_team_id"] is None
    assert played["line_results"] == []

    home = s.refresh_team("th")
    assert home["standings_points"] == 0
    assert home["matches_won"] == 0

    _cards, meta = validate_paginated(
        api.list_scorecards(
            SECTION_ADMIN,
            {"match_id": s.matches["m1"]["id"], "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 0


def _ledger_lines(s):
    """Home takes lines 1 and 2 (12-7, 12-0) and loses line 3 (7-12)."""
    return [
        f.scorecard_line(
            1,
            [s.player_id("ph1"), s.player_id("ph2")],
            [s.player_id("pa1"), s.player_id("pa2")],
            [f.set_score(6, 4), f.set_score(6, 3)],
        ),
        f.scorecard_line(
            2,
            [s.player_id("ph3"), s.player_id("ph4")],
            [s.player_id("pa3"), s.player_id("pa4")],
            [f.set_score(6, 0), f.set_score(6, 0)],
        ),
        f.scorecard_line(
            3,
            [s.player_id("ph5"), s.player_id("ph6")],
            [s.player_id("pa5"), s.player_id("pa6")],
            [f.set_score(4, 6), f.set_score(3, 6)],
        ),
    ]


def _played_match_with_a_card_awaiting_review(api):
    """M1 is PLAYED at 21:00Z with the home captain's three-line card SUBMITTED."""
    s = six_a_side_league(api)
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.confirm_match("m1")
    s.set_clock("2026-08-15T21:00:00Z")
    s.mark_played("m1")
    s.submit_scorecard("m1", _ledger_lines(s))
    return s


def test_one_verification_reconciles_the_match_both_teams_and_the_league(api):
    """A single VERIFY writes match aggregates, both ledgers and the eligibility counters.

    PRD 3.6: "At the second level, both teams recompute `matches_won`,
    `matches_lost`, `lines_won`, `lines_lost`, `sets_won`, `sets_lost`, `games_won`,
    `games_lost` and `standings_points` on the official basis."

    Design: Corner/state_machines/scorecard_verification_syncs_team_ledgers_and_league_invariant_in_one_request
    """
    s = _played_match_with_a_card_awaiting_review(api)
    verified = s.review_scorecard()
    assert verified["status"] == SCORECARD_VERIFIED
    assert verified["verified_by_captain_player_id"] == s.player_id("pa1")
    assert_instant_equals(verified["verified_at"], "2026-08-15T21:00:00Z")

    match = s.refresh_match("m1")
    assert match["result_status"] == RESULT_VERIFIED
    assert match["schedule_status"] == SCHED_PLAYED
    assert match["winner_team_id"] == s.teams["th"]["id"]
    assert match["home_lines_won"] == 2
    assert match["away_lines_won"] == 1
    assert match["home_sets_won"] == 4
    assert match["away_sets_won"] == 2
    assert match["home_games_won"] == 31
    assert match["away_games_won"] == 19

    home = s.refresh_team("th")
    assert home["matches_won"] == 1
    assert home["matches_lost"] == 0
    assert home["lines_won"] == 2
    assert home["lines_lost"] == 1
    assert home["sets_won"] == 4
    assert home["sets_lost"] == 2
    assert home["games_won"] == 31
    assert home["games_lost"] == 19
    assert home["standings_points"] == 5

    away = s.refresh_team("ta")
    assert away["matches_won"] == 0
    assert away["matches_lost"] == 1
    assert away["lines_won"] == 1
    assert away["lines_lost"] == 2
    assert away["sets_won"] == 2
    assert away["sets_lost"] == 4
    assert away["games_won"] == 19
    assert away["games_lost"] == 31
    assert away["standings_points"] == 1

    # The league's line ledger and points ledger both close exactly.
    assert match["home_lines_won"] + match["away_lines_won"] == 3
    assert home["lines_won"] + away["lines_won"] == 3
    assert home["standings_points"] + away["standings_points"] == 6

    captain = s.refresh_player("ph1")
    assert captain["verified_match_count"] == 1
    assert captain["verified_line_count"] == 1

    spot = s.refresh_spot("ph1")
    assert spot["verified_match_count"] == 1
    assert spot["playoff_eligible"] is True
    assert s.refresh_team("th")["playoff_eligible_roster_size"] == 6


def test_a_verified_card_admits_no_amendment_and_its_credit_does_not_move(api):
    """VERIFIED is terminal on the card, so amendment has no declared edge at all.

    PRD 2.9: "`ERR_INVALID_STATE` - a transition from the resource's current state is
    declared for this action."

    Design: Corner/state_machines/amend_after_verification_returns_invalid_state_and_leaves_the_verified_result_intact
    """
    s = _played_match_with_a_card_awaiting_review(api)
    s.review_scorecard()
    card_id = s.scorecards["sc1"]["id"]

    sweep = [
        f.scorecard_line(
            line_number,
            [s.player_id(f"ph{2 * line_number - 1}"), s.player_id(f"ph{2 * line_number}")],
            [s.player_id(f"pa{2 * line_number - 1}"), s.player_id(f"pa{2 * line_number}")],
            [f.set_score(6, 0), f.set_score(6, 0)],
        )
        for line_number in (1, 2, 3)
    ]
    response = api.amend_scorecard(card_id, {"lines": sweep}, s.captain_headers("th"))
    validate_error(response, ERR_INVALID_STATE, 409)

    reported = response.json()["data"]["error_id"]
    assert reported != ERR_SCORECARD_STATE_FORBIDS_ACTION
    assert reported != ERR_MATCH_RESULT_STATE_INVALID

    card = get_success_data(api.get_scorecard(card_id, SECTION_ADMIN))
    assert card["status"] == SCORECARD_VERIFIED
    assert card["amendment_count"] == 0

    match = s.refresh_match("m1")
    assert match["result_status"] == RESULT_VERIFIED
    assert match["home_games_won"] == 31
    assert match["away_games_won"] == 19

    home = s.refresh_team("th")
    assert home["standings_points"] == 5
    assert home["lines_won"] == 2
    away = s.refresh_team("ta")
    assert away["standings_points"] == 1
    assert away["lines_won"] == 1
