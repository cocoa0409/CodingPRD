"""Four-level cascades fired by three different triggering transitions."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.constants import (
    APPEAL_GRANTED,
    APPEAL_UP,
    DEFAULT_KIND_NO_SHOW,
    GRIEVANCE_INELIGIBLE_LINEUP,
    GRIEVANCE_UPHELD,
    INELIGIBLE_APPEAL_GRANTED,
    INELIGIBLE_GRIEVANCE_REMEDY,
    INELIGIBLE_PLAYER_SUSPENDED,
    OUTCOME_GRANT,
    OUTCOME_UPHOLD,
    PLAYER_ACTIVE,
    PLAYER_STRIKE_SUSPENDED,
    RATING_APPEAL_GRANTED,
    REMEDY_TEAM_DISQUALIFICATION,
    RESULT_PENDING,
    RESULT_VERIFIED,
    SCHED_CANCELLED,
    SCHED_DEFAULTED,
    SIDE_HOME,
    SPOT_ACTIVE,
    SPOT_INELIGIBLE,
    STRIKE_SCORECARD_FALSIFICATION,
    SUBJECT_GRIEVANCE,
    SUBJECT_RATING_APPEAL,
    TEAM_DISQUALIFIED,
    TEAM_IN_PLAY,
    VOTE_SUPPORT,
)
from test_helpers.fixtures import two_team_league
from test_helpers.test_users import LEAGUE_COORDINATOR, make_player_headers


# ---------------------------------------------------------------------------
# Instance: strike_suspension_cascades_player_to_spot_to_team_to_league
# ---------------------------------------------------------------------------
def _league_in_play_then_one_weight_three_strike(api):
    s = two_team_league(
        api,
        roster_size=2,
        section_kwargs={
            "min_matches_for_playoff_eligibility": 1,
            "strike_limit": 3,
            "disqualification_strike_limit": 6,
        },
    )
    assert s.refresh_player("ph2")["strike_count"] == 0
    assert s.refresh_league()["noncompliant_team_count"] == 0
    strike = get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("ph2"),
                STRIKE_SCORECARD_FALSIFICATION,
                reason="Submitted a fabricated line score",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    return s, strike


def test_one_weight_three_strike_drives_player_spot_team_and_league(api):
    """A single request reaches the ledger, the spot, the team and the league.

    PRD 3.7: "When a player crosses into `STRIKE_SUSPENDED`, every roster spot of
    that player at `ACTIVE` transitions to `INELIGIBLE` with `ineligible_reason`
    set to `PLAYER_SUSPENDED` and `source_strike_id` set to the identifier of the
    strike that just crossed the threshold."

    Design: Difficulty/transitive_cascade/strike_suspension_cascades_player_to_spot_to_team_to_league
    """
    s, strike = _league_in_play_then_one_weight_three_strike(api)
    assert strike["weight"] == 3

    player = s.refresh_player("ph2")
    assert player["strike_count"] == 3
    assert player["status"] == PLAYER_STRIKE_SUSPENDED

    spot = s.refresh_spot("ph2")
    assert spot["status"] == SPOT_INELIGIBLE
    assert spot["ineligible_reason"] == INELIGIBLE_PLAYER_SUSPENDED
    assert spot["source_strike_id"] == strike["id"]

    team = s.refresh_team("th")
    assert team["active_roster_size"] == 1
    assert team["roster_compliant"] is False
    assert team["status"] == TEAM_IN_PLAY
    assert s.refresh_league()["noncompliant_team_count"] == 1


def test_the_strike_cascade_stops_at_the_charged_players_own_team(api):
    """The opposing team and the charged player's team-mate are untouched.

    PRD 3.7: "Each affected team then recomputes `active_roster_size`,
    `playoff_eligible_roster_size` and `roster_compliant`, and each affected
    league recomputes `noncompliant_team_count`."

    Design: Difficulty/transitive_cascade/strike_suspension_cascades_player_to_spot_to_team_to_league
    """
    s, _strike = _league_in_play_then_one_weight_three_strike(api)

    away = s.refresh_team("ta")
    assert away["active_roster_size"] == 2
    assert away["roster_compliant"] is True
    assert away["status"] == TEAM_IN_PLAY

    assert s.refresh_player("ph1")["status"] == PLAYER_ACTIVE
    assert s.refresh_player("ph1")["strike_count"] == 0
    assert s.refresh_spot("ph1")["status"] == SPOT_ACTIVE
    assert s.refresh_spot("pa1")["status"] == SPOT_ACTIVE
    assert s.refresh_spot("pa2")["status"] == SPOT_ACTIVE
    assert s.refresh_player("pa2")["strike_count"] == 0


# ---------------------------------------------------------------------------
# Instance: appeal_grant_up_cascades_rating_to_spot_to_team_to_league
# ---------------------------------------------------------------------------
def _quorum_backed_up_appeal_out_of_the_league_band(api):
    """h2 sits in a 3.5 league and appeals up to 4.0 with two SUPPORT votes."""
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
    get_success_data(
        api.create_committee_vote(
            f.vote_payload(
                appeal["id"],
                VOTE_SUPPORT,
                SUBJECT_RATING_APPEAL,
                note="Level is clearly understated",
            ),
            s.member_headers("pc1"),
        ),
        201,
    )
    get_success_data(
        api.create_committee_vote(
            f.vote_payload(appeal["id"], VOTE_SUPPORT, SUBJECT_RATING_APPEAL),
            s.member_headers("pc2"),
        ),
        201,
    )
    return s, appeal


def test_an_upward_grant_pushes_the_appellant_out_of_the_band_and_off_the_roster(api):
    """A pure rating write cascades to spot, team and league with no match at all.

    PRD 3.8: "Then, **for an `UP` direction only**, every roster spot of that
    player at `ACTIVE` whose team's league has an `ntrp_level` below the player's
    new `rating_level` transitions to `INELIGIBLE` with `ineligible_reason`
    `APPEAL_GRANTED` and `source_strike_id` left null"

    Design: Difficulty/transitive_cascade/appeal_grant_up_cascades_rating_to_spot_to_team_to_league
    """
    s, appeal = _quorum_backed_up_appeal_out_of_the_league_band(api)

    decided = get_success_data(
        api.decide_appeal(
            appeal["id"],
            {"outcome": OUTCOME_GRANT, "decision_note": "Quorum reached 2-0"},
            s.chair_headers(),
        )
    )
    assert decided["status"] == APPEAL_GRANTED
    assert decided["granted_level"] == 4.0
    assert decided["auto_grant_eligible"] is False
    assert decided["support_vote_count"] == 2
    assert decided["oppose_vote_count"] == 0
    assert decided["decided_by_chair_player_id"] == s.player_id("pch")

    player = s.refresh_player("ph2")
    assert player["rating_level"] == 4.0
    assert player["rating_type"] == RATING_APPEAL_GRANTED

    spot = s.refresh_spot("ph2")
    assert spot["status"] == SPOT_INELIGIBLE
    assert spot["ineligible_reason"] == INELIGIBLE_APPEAL_GRANTED
    assert spot["source_strike_id"] is None
    assert spot["level_at_add"] == 3.5


def test_the_grant_cascade_flips_only_the_appellants_team_out_of_compliance(api):
    """Team H drops to one active spot; Team A never moves.

    PRD 3.8: "each affected team recomputes `active_roster_size`,
    `playoff_eligible_roster_size` and `roster_compliant`; and each affected
    league recomputes `noncompliant_team_count`."

    Design: Difficulty/transitive_cascade/appeal_grant_up_cascades_rating_to_spot_to_team_to_league
    """
    s, appeal = _quorum_backed_up_appeal_out_of_the_league_band(api)
    get_success_data(
        api.decide_appeal(
            appeal["id"],
            {"outcome": OUTCOME_GRANT, "decision_note": "Quorum reached 2-0"},
            s.chair_headers(),
        )
    )

    home = s.refresh_team("th")
    assert home["active_roster_size"] == 1
    assert home["roster_compliant"] is False
    assert s.refresh_league()["noncompliant_team_count"] == 1

    away = s.refresh_team("ta")
    assert away["roster_compliant"] is True
    assert away["active_roster_size"] == 2
    assert s.refresh_spot("pa2")["status"] == SPOT_ACTIVE
    assert s.refresh_player("pa2")["rating_level"] == 3.5

    # No strike machinery was involved anywhere in this cascade.
    assert s.refresh_player("ph2")["strike_count"] == 0


# ---------------------------------------------------------------------------
# Instance: grievance_team_disqualification_cascades_spots_matches_and_counters
# ---------------------------------------------------------------------------
def _upheld_disqualification_grievance(api):
    s = two_team_league(api, roster_size=2, with_committee=True)
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.set_clock("2026-08-15T18:00:00Z")
    s.default_match("m1", SIDE_HOME, DEFAULT_KIND_NO_SHOW)

    s.create_match("m2", "th", "ta", round_number=2)
    s.schedule_match("m2", "2026-08-16T18:00:00Z", 3)

    grievance = get_success_data(
        api.create_grievance(
            f.grievance_payload(
                s.league["id"],
                s.teams["th"]["id"],
                GRIEVANCE_INELIGIBLE_LINEUP,
                subject_match_id=s.matches["m1"]["id"],
                statement=(
                    "Team H fielded unactivated players in round 1 before defaulting"
                ),
            ),
            s.captain_headers("ta"),
        ),
        201,
    )
    get_success_data(api.start_grievance_review(grievance["id"], s.chair_headers()))
    for member in ("pc1", "pc2"):
        get_success_data(
            api.create_committee_vote(
                f.vote_payload(grievance["id"], VOTE_SUPPORT, SUBJECT_GRIEVANCE),
                s.member_headers(member),
            ),
            201,
        )
    decided = get_success_data(
        api.decide_grievance(
            grievance["id"],
            {
                "outcome": OUTCOME_UPHOLD,
                "remedy": REMEDY_TEAM_DISQUALIFICATION,
                "decision_note": "Repeat roster violations",
            },
            s.chair_headers(),
        )
    )
    return s, decided


def test_disqualification_freezes_the_team_and_marks_every_active_spot(api):
    """Both spots carry GRIEVANCE_REMEDY, a reason no rescission can undo.

    PRD 3.8: "**The `TEAM_DISQUALIFICATION` remedy** takes the accused team to
    `DISQUALIFIED` from either `ROSTER_LOCKED` or `IN_PLAY`. Every roster spot of
    that team at `ACTIVE` transitions to `INELIGIBLE` with `ineligible_reason`
    `GRIEVANCE_REMEDY`."

    Design: Difficulty/transitive_cascade/grievance_team_disqualification_cascades_spots_matches_and_counters
    """
    s, decided = _upheld_disqualification_grievance(api)
    assert decided["status"] == GRIEVANCE_UPHELD
    assert decided["remedy"] == REMEDY_TEAM_DISQUALIFICATION
    assert decided["support_vote_count"] == 2

    home = s.refresh_team("th")
    assert home["status"] == TEAM_DISQUALIFIED
    assert home["active_roster_size"] == 0
    assert home["roster_compliant"] is False

    for key in ("ph1", "ph2"):
        spot = s.refresh_spot(key)
        assert spot["status"] == SPOT_INELIGIBLE
        assert spot["ineligible_reason"] == INELIGIBLE_GRIEVANCE_REMEDY

    h1 = s.refresh_player("ph1")
    assert h1["strike_count"] == 1
    assert h1["status"] == PLAYER_ACTIVE


def test_disqualification_cancels_only_the_uncontested_fixture_and_keeps_history(api):
    """M2 is cancelled, M1 keeps its default credits, and both counters move.

    PRD 3.8: "Every match involving that team whose `schedule_status` is
    `SCHEDULED` or `CONFIRMED` and whose `result_status` is still `PENDING` has
    its `schedule_status` taken to `CANCELLED`. Matches already `VERIFIED` or
    `FINALIZED` **keep** their standings contributions - a disqualification is
    forward-looking and does not rewrite history."

    Design: Difficulty/transitive_cascade/grievance_team_disqualification_cascades_spots_matches_and_counters
    """
    s, _decided = _upheld_disqualification_grievance(api)

    m2 = s.refresh_match("m2")
    assert m2["schedule_status"] == SCHED_CANCELLED
    assert m2["result_status"] == RESULT_PENDING

    m1 = s.refresh_match("m1")
    assert m1["schedule_status"] == SCHED_DEFAULTED
    assert m1["result_status"] == RESULT_VERIFIED

    away = s.refresh_team("ta")
    assert away["matches_won"] == 1
    assert away["lines_won"] == 3
    assert away["games_won"] == 36
    assert away["standings_points"] == 6

    league = s.refresh_league()
    assert league["registered_team_count"] == 1
    assert league["noncompliant_team_count"] == 0
