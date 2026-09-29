"""Two named variants of one calculation that must disagree over identical data."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.assertions import standings_by_team
from test_helpers.constants import (
    RATING_COMPUTER_RATED,
    RATING_PERIOD_OPEN_SEASON,
    RATING_PERIOD_RECALC_IN_PROGRESS,
    RATING_PERIOD_RECALC_PUBLISHED,
    RESULT_REPORTED,
    RESULT_VERIFIED,
    SPOT_ACTIVE,
)
from test_helpers.fixtures import (
    played_match,
    regular_plus_playoff_season,
    six_a_side_league,
    standard_three_lines,
)
from test_helpers.test_users import LEAGUE_COORDINATOR, SECTION_ADMIN


# ---------------------------------------------------------------------------
# Instance: dynamic_rating_in_season_recency_vs_year_end_playoff_weight
# ---------------------------------------------------------------------------
def test_in_season_dynamic_rating_ignores_the_playoff_weight_the_year_end_run_applies(
    api,
):
    """h1's two lines average to 3.783 live but weight to 3.740 at year end.

    PRD 3.2: "The **year-end final** variant is computed during the year-end
    recalculation and written to `Player.proposed_recalc_dynamic`. It has no
    recency cap - every counted line of the whole season is included - and it
    weights lines by competitive stage: a line whose owning match has `stage`
    `PLAYOFF` carries a weight of 1.5, and a line whose owning match has `stage`
    `REGULAR` carries a weight of 1.0."

    Design: Difficulty/dual_variant_calc/dynamic_rating_in_season_recency_vs_year_end_playoff_weight
    """
    s = regular_plus_playoff_season(api)

    before = s.refresh_player("ph1")
    assert before["dynamic_rating"] == 3.783
    assert before["proposed_recalc_dynamic"] is None
    assert before["proposed_recalc_level"] is None

    get_success_data(api.year_end_recalc(s.section["id"], SECTION_ADMIN))

    after = s.refresh_player("ph1")
    assert after["dynamic_rating"] == 3.783
    assert after["proposed_recalc_dynamic"] == 3.740
    assert after["dynamic_rating"] != after["proposed_recalc_dynamic"]
    assert after["verified_line_count"] == 2
    assert after["verified_match_count"] == 2
    assert after["proposed_recalc_level"] == 4.0
    assert after["rating_level"] == 4.0
    assert after["rating_type"] == RATING_COMPUTER_RATED


def test_the_two_variants_diverge_in_both_directions_across_the_same_roster(api):
    """h3 falls 3.750 to 3.724 while h5 rises 3.825 to 3.860 in the same run.

    PRD 3.2: "The **in-season provisional** variant is the one written to
    `Player.dynamic_rating`."

    Design: Difficulty/dual_variant_calc/dynamic_rating_in_season_recency_vs_year_end_playoff_weight
    """
    s = regular_plus_playoff_season(api)
    get_success_data(api.year_end_recalc(s.section["id"], SECTION_ADMIN))

    h3 = s.refresh_player("ph3")
    assert h3["dynamic_rating"] == 3.750
    assert h3["proposed_recalc_dynamic"] == 3.724

    h5 = s.refresh_player("ph5")
    assert h5["dynamic_rating"] == 3.825
    assert h5["proposed_recalc_dynamic"] == 3.860

    a1 = s.refresh_player("pa1")
    assert a1["dynamic_rating"] == 3.967
    assert a1["proposed_recalc_dynamic"] == 4.010

    assert s.refresh_player("pa2")["proposed_recalc_level"] == 4.0

    section = get_success_data(api.get_section(s.section["id"], SECTION_ADMIN))
    assert section["rating_period_status"] == RATING_PERIOD_RECALC_IN_PROGRESS
    assert section["recalculated_player_count"] == 12


# ---------------------------------------------------------------------------
# Instance: standings_official_persisted_vs_provisional_reported_basis
# ---------------------------------------------------------------------------
def _one_verified_and_one_reported_match(api):
    s = six_a_side_league(api)
    played_match(s, standard_three_lines(s), match_key="m1")

    s.create_match("m3", "th", "ta", round_number=2)
    s.schedule_match("m3", "2026-08-20T18:00:00Z", 3)
    s.confirm_match("m3")
    s.set_clock("2026-08-20T21:00:00Z")
    s.mark_played("m3")
    away_sweep = [
        f.scorecard_line(
            number,
            [s.player_id(home), s.player_id(home_partner)],
            [s.player_id(away), s.player_id(away_partner)],
            [f.set_score(2, 6), f.set_score(2, 6)],
        )
        for number, home, home_partner, away, away_partner in (
            (1, "ph1", "ph2", "pa1", "pa2"),
            (2, "ph3", "ph4", "pa3", "pa4"),
            (3, "ph5", "ph6", "pa5", "pa6"),
        )
    ]
    get_success_data(
        api.create_scorecard(
            f.scorecard_payload(s.matches["m3"]["id"], away_sweep),
            s.captain_headers("ta"),
        ),
        201,
    )
    return s


def test_official_standings_ignore_the_reported_match_the_provisional_basis_counts(api):
    """The away team is persisted at 1 point yet reads 7 on the other basis.

    PRD 3.6: "The official inclusion set is `VERIFIED` and `FINALIZED`. The
    provisional inclusion set is `REPORTED`, `VERIFIED` and `FINALIZED`."

    Design: Difficulty/dual_variant_calc/standings_official_persisted_vs_provisional_reported_basis
    """
    s = _one_verified_and_one_reported_match(api)
    assert s.refresh_match("m1")["result_status"] == RESULT_VERIFIED
    assert s.refresh_match("m3")["result_status"] == RESULT_REPORTED

    away = s.refresh_team("ta")
    assert away["standings_points"] == 1
    assert away["matches_won"] == 0
    assert away["matches_lost"] == 1
    assert away["lines_won"] == 1

    provisional = standings_by_team(
        api, s.league["id"], LEAGUE_COORDINATOR, "provisional"
    )
    away_row = provisional[away["id"]]
    assert away_row["standings_points"] == 7
    assert away_row["matches_won"] == 1
    assert away_row["matches_lost"] == 1
    assert away_row["lines_won"] == 4
    assert away["standings_points"] != away_row["standings_points"]


def test_the_home_team_reads_the_same_five_points_on_both_bases(api):
    """A test cannot pass by inflating both bases: home is 5 either way.

    PRD 3.6: "A team's official standings are persisted onto its own fields on
    every result transition, and the same arithmetic can also be read on a
    provisional basis through the `basis` query parameter of the standings
    listing, which accepts `official` (the default) and `provisional`."

    Design: Difficulty/dual_variant_calc/standings_official_persisted_vs_provisional_reported_basis
    """
    s = _one_verified_and_one_reported_match(api)
    home = s.refresh_team("th")
    assert home["standings_points"] == 5
    assert home["matches_won"] == 1
    assert home["lines_won"] == 2
    assert home["games_won"] == 32

    official = standings_by_team(api, s.league["id"], LEAGUE_COORDINATOR)
    assert official[home["id"]]["standings_points"] == 5

    provisional = standings_by_team(
        api, s.league["id"], LEAGUE_COORDINATOR, "provisional"
    )
    home_row = provisional[home["id"]]
    assert home_row["standings_points"] == 5
    assert home_row["matches_won"] == 1
    assert home_row["matches_lost"] == 1
    assert home_row["lines_won"] == 2

    # The provisional read is never persisted onto the team row.
    assert s.refresh_team("th")["standings_points"] == 5
    assert s.refresh_team("ta")["standings_points"] == 1


# ---------------------------------------------------------------------------
# Instance: recalc_propose_epoch_scope_vs_publish_epoch_change_count
# ---------------------------------------------------------------------------
def _single_regular_match_season(api):
    """Every player owns exactly one counted line, isolating propose vs publish."""
    s = six_a_side_league(api, away_levels=[4.0, 3.5, 4.0, 3.5, 4.0, 3.5])
    played_match(s, standard_three_lines(s), match_key="m1")
    return s


def test_propose_phase_scopes_every_eligible_player_including_unchanged_levels(api):
    """Twelve players are in scope and none of their levels move yet.

    PRD 3.9: "The section's `recalculated_player_count` is set to the number of
    players in scope, `rating_period_status` becomes `RECALC_IN_PROGRESS`, and
    the section's `version` increases by 1."

    Design: Difficulty/dual_variant_calc/recalc_propose_epoch_scope_vs_publish_epoch_change_count
    """
    s = _single_regular_match_season(api)
    before = get_success_data(api.get_section(s.section["id"], SECTION_ADMIN))
    assert before["rating_period_status"] == RATING_PERIOD_OPEN_SEASON
    assert before["recalc_run_index"] == 0
    assert before["recalculated_player_count"] == 0
    assert before["published_level_change_count"] == 0

    get_success_data(api.year_end_recalc(s.section["id"], SECTION_ADMIN))

    section = get_success_data(api.get_section(s.section["id"], SECTION_ADMIN))
    assert section["rating_period_status"] == RATING_PERIOD_RECALC_IN_PROGRESS
    assert section["recalculated_player_count"] == 12
    assert section["published_level_change_count"] == 0

    # Proposed unchanged for h1 (delta 0.000) and proposed down for h5 (-0.350).
    h1 = s.refresh_player("ph1")
    assert h1["proposed_recalc_dynamic"] == 4.000
    assert h1["proposed_recalc_level"] == 4.0
    assert h1["rating_level"] == 4.0
    h5 = s.refresh_player("ph5")
    assert h5["proposed_recalc_dynamic"] == 3.650
    assert h5["proposed_recalc_level"] == 3.5
    assert h5["rating_level"] == 4.0


def test_publish_phase_counts_only_the_five_levels_that_actually_crossed(api):
    """Twelve proposals publish, but only five rating levels genuinely changed.

    PRD 3.9: "The section's `published_level_change_count` counts only the
    players whose level genuinely changed, so it is generally smaller than
    `recalculated_player_count`."

    Design: Difficulty/dual_variant_calc/recalc_propose_epoch_scope_vs_publish_epoch_change_count
    """
    s = _single_regular_match_season(api)
    get_success_data(api.year_end_recalc(s.section["id"], SECTION_ADMIN))
    get_success_data(api.publish_recalc(s.section["id"], SECTION_ADMIN))

    section = get_success_data(api.get_section(s.section["id"], SECTION_ADMIN))
    assert section["rating_period_status"] == RATING_PERIOD_RECALC_PUBLISHED
    assert section["recalculated_player_count"] == 12
    assert section["published_level_change_count"] == 5
    assert section["recalc_run_index"] == 1

    # The two demotions: delta of exactly -0.350 crosses the downward threshold.
    h5 = s.refresh_player("ph5")
    assert h5["rating_level"] == 3.5
    assert h5["proposed_recalc_level"] == 3.5
    assert h5["dynamic_rating"] == 3.650
    assert s.refresh_player("ph6")["rating_level"] == 3.5

    # The three promotions all started from 3.5 and crossed +0.25 or better.
    assert s.refresh_player("pa2")["rating_level"] == 4.0
    assert s.refresh_player("pa2")["rating_type"] == RATING_COMPUTER_RATED
    assert s.refresh_player("pa4")["rating_level"] == 4.0
    assert s.refresh_player("pa6")["rating_level"] == 4.0

    # Unchanged levels: h1 held at 4.0 and a1 (-0.250) and a5 (+0.100) held too.
    h1 = s.refresh_player("ph1")
    assert h1["rating_level"] == 4.0
    assert h1["rating_type"] == RATING_COMPUTER_RATED
    assert h1["proposed_recalc_level"] == 4.0
    assert s.refresh_player("pa1")["rating_level"] == 4.0
    a5 = s.refresh_player("pa5")
    assert a5["rating_level"] == 4.0
    assert a5["dynamic_rating"] == 4.100

    assert s.refresh_spot("pa2")["status"] == SPOT_ACTIVE
    assert s.refresh_spot("ph5")["status"] == SPOT_ACTIVE
    assert s.refresh_league()["noncompliant_team_count"] == 0
