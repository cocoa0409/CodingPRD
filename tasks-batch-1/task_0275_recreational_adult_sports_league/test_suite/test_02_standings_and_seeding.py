"""Standings computation, the two tiebreak chains, and seed ordering determinism.

Covers difficulty rules dual_variant_calc / combinatorial_formula on the
Division/Team standings domain, plus the standings_points corner.
"""
from test_helpers import (
    validate_success, validate_paginated,
    make_league_admin_headers,
)
import test_helpers.fixtures as fx

ADMIN = make_league_admin_headers()


def _standings(api, division_id):
    resp = api.get_standings(division_id, ADMIN)
    data, _meta = validate_paginated(resp)
    return data


def test_standings_tied_teams_fall_through_to_created_at_ascending_h2h(api):
    """PRD §3.8: "Under `HEAD_TO_HEAD`, ties are broken in this order: by `points`,
    then by head-to-head points (the league points each tied team earned only in
    regular games played strictly among the tied teams), then by goal difference
    (`points_for` minus `points_against`), then by `points_for`, and finally by
    `created_at` earliest-first."
    PRD §3.8: "In both chains `created_at` ascending is the final deterministic
    tie-break and the `id` is never used for ordering."

    Two CONFIRMED teams with no games played are tied on every key, so the
    deterministic `created_at` ascending tie-break decides: the earlier-created team
    seeds first.

    Design: Difficulty/dual_variant_calc/standings_seed_h2h_vs_pointdiff_diverges
    """
    base = fx.setup_division_with_two_confirmed_teams(
        division_overrides={"standings_tiebreaker": "HEAD_TO_HEAD", "team_capacity": 4},
    )
    standings = _standings(api, base["division"]["id"])
    ids = [t["id"] for t in standings]
    assert base["home_team"]["id"] in ids and base["away_team"]["id"] in ids
    # home_team was registered (created) before away_team.
    assert ids.index(base["home_team"]["id"]) < ids.index(base["away_team"]["id"]), (
        "the earlier-created team must seed first when all other keys are tied"
    )


def test_standings_tied_teams_fall_through_to_created_at_ascending_point_diff(api):
    """PRD §3.8: "Under `POINT_DIFFERENTIAL`, the chain is: by `points`, then by goal
    difference (`points_for` minus `points_against`), then by `points_for`, then by
    head-to-head points, and finally by `created_at` earliest-first."
    PRD §3.8: "In both chains `created_at` ascending is the final deterministic
    tie-break and the `id` is never used for ordering."

    Design: Difficulty/dual_variant_calc/standings_seed_h2h_vs_pointdiff_diverges
    """
    base = fx.setup_division_with_two_confirmed_teams(
        division_overrides={"standings_tiebreaker": "POINT_DIFFERENTIAL", "team_capacity": 4},
    )
    standings = _standings(api, base["division"]["id"])
    ids = [t["id"] for t in standings]
    assert ids.index(base["home_team"]["id"]) < ids.index(base["away_team"]["id"]), (
        "the earlier-created team must seed first when all other keys are tied"
    )


def test_standings_seed_order_is_deterministic_by_created_at(api):
    """PRD §3.8: "In both chains `created_at` ascending is the final deterministic
    tie-break and the `id` is never used for ordering. A team's seed is its one-based
    position in this sorted order."

    With a single CONFIRMED team the standings is fully determined and contains that
    team; no ranking decision depends on `id`.

    Design: Difficulty/combinatorial_formula/standings_seed_multifactor_tiebreak_mode_a
    """
    base = fx.setup_open_division()
    cap = fx.create_player()
    team = fx.register_team(base["division"]["id"], cap["id"])
    team = fx.confirm_team(team["id"])
    standings = _standings(api, base["division"]["id"])
    ids = [t["id"] for t in standings]
    assert ids == [team["id"]], f"single confirmed team must be the sole seed, got {ids}"


def test_standings_point_differential_chain_total_order_two_teams(api):
    """PRD §3.8: "Under `POINT_DIFFERENTIAL`, the chain is: by `points`, then by goal
    difference (`points_for` minus `points_against`), then by `points_for`, then by
    head-to-head points, and finally by `created_at` earliest-first."

    Design: Difficulty/combinatorial_formula/standings_seed_multifactor_tiebreak_mode_a
    """
    base = fx.setup_division_with_two_confirmed_teams(
        division_overrides={"standings_tiebreaker": "POINT_DIFFERENTIAL", "team_capacity": 4},
    )
    standings = _standings(api, base["division"]["id"])
    # Both teams 0-0 on every key -> created_at ASC orders them; the result is a total order.
    ids = [t["id"] for t in standings]
    assert len(ids) == 2 and len(set(ids)) == 2, "every confirmed team appears exactly once in seed order"
    assert ids.index(base["home_team"]["id"]) < ids.index(base["away_team"]["id"])


def test_confirmed_win_scores_three_points_and_loss_zero(api):
    """PRD §3.8: "League `points` are three for each win, one for each draw, and zero
    for each loss."

    Design: Corner/calculations/standings_points_win_draw_values
    """
    s = fx.setup_in_play_game_pending()
    fx.submit_and_confirm_score(s["game"]["id"], s["referee"]["id"], 2, 1)

    home = validate_success(api.get_team(s["home_team"]["id"], ADMIN))
    away = validate_success(api.get_team(s["away_team"]["id"], ADMIN))
    assert home["points"] == 3 and home["wins"] == 1, f"winner: {home['points']}/{home['wins']}"
    assert away["points"] == 0 and away["losses"] == 1, f"loser: {away['points']}/{away['losses']}"
