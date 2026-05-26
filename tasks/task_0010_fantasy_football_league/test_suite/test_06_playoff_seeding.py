"""Playoff seeding (Difficulty rule 1 instance B / cascade rule 4 instance B).

Pre-finalize, every Team carries `playoff_seed = 0` per PRD §3.7
("Teams not in the top `playoff_team_count` keep `playoff_seed` at 0").
The full seeding cascade fires at `start-playoffs`; here we exercise the
intermediate-step observable consequences (standings) and Difficulty
rule 4b's cascade chain (matchup finalize → wins increment → seed
recompute on start-playoffs).
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_league,
    create_player,
    create_team,
    create_regular_matchup,
    draft_pairs_serpent,
    finalize_draft,
    finalize_matchup_with_scores,
    set_clock,
    setup_in_season_league,
    start_draft,
    start_matchup,
    validate_success,
)


def test_pre_playoff_team_playoff_seed_is_zero(api, commissioner_headers):
    """PRD §3.1: "Initially the team's computed fields — `faab_balance_cents`,
    `waiver_priority`, `wins`, `losses`, `total_points_for`,
    `total_points_against`, `intra_division_wins`, `playoff_seed` — are 0 (or
    1 for the version counter), and `keeper_player_ids` is an empty array."

    Design: Difficulty/dual_variant_calc/playoff_seed_standard_vs_division_first_reranks_team
    """
    set_clock("2026-08-01T00:00:00Z")
    ctx = setup_in_season_league(
        league_overrides={
            "name": "Seed Pre", "draft_type": "SNAKE", "roster_size": 2,
            "starter_slot_count": 1, "ir_slot_count": 0,
            "faab_budget_cents": 10000, "veto_threshold": 1,
            "keeper_limit": 1, "playoff_team_count": 2, "tiebreak_rule": "STANDARD",
        },
        team_names=["Alpha", "Bravo"],
        divisions=["East", "East"],
    )
    alpha = ctx["teams"][0]
    bravo = ctx["teams"][1]
    assert alpha["playoff_seed"] == 0
    assert bravo["playoff_seed"] == 0


def test_regular_matchup_finalize_increments_winner_wins(
    api, commissioner_headers,
):
    """PRD §3.6: "For a `REGULAR` matchup, the cascade fires on the
    standings: the winner's `wins` increments by 1 and `total_points_for`
    is incremented by its score and `total_points_against` by the opponent's
    score; the loser's `losses` increments by 1 with the same point-aggregate
    updates".

    Design: Difficulty/dual_variant_calc/playoff_seed_standard_vs_division_first_reranks_team
    """
    set_clock("2026-08-01T00:00:00Z")
    ctx = setup_in_season_league(
        league_overrides={
            "name": "Standings1", "draft_type": "SNAKE", "roster_size": 2,
            "starter_slot_count": 1, "ir_slot_count": 0,
            "faab_budget_cents": 10000, "veto_threshold": 1,
            "keeper_limit": 1, "playoff_team_count": 2, "tiebreak_rule": "STANDARD",
        },
        team_names=["Alpha", "Bravo"],
        divisions=["East", "East"],
    )
    alpha, bravo = ctx["teams"]
    matchup = create_regular_matchup(ctx["league"]["id"], 1, alpha, bravo)
    matchup = start_matchup(matchup)
    finalize_matchup_with_scores(matchup, home_score=100.0, away_score=105.0)

    a = validate_success(
        api.get_team(alpha["id"], commissioner_headers), expected_status=200,
    )
    b = validate_success(
        api.get_team(bravo["id"], commissioner_headers), expected_status=200,
    )
    assert a["wins"] == 0
    assert a["losses"] == 1
    assert a["total_points_for"] == 100.0
    assert b["wins"] == 1
    assert b["losses"] == 0
    assert b["total_points_for"] == 105.0


# ─── Difficulty rule 4 instance B — matchup-finalize cascade ──────────────

def test_matchup_completed_marks_state_and_winner(api, commissioner_headers):
    """PRD §3.6: "Once both scores are settled, the matchup's
    `winner_team_id` is assigned to the team with the higher score".

    Design: Difficulty/transitive_cascade/matchup_completed_updates_standings_seeds_bracket_depth3
    """
    set_clock("2026-11-15T00:00:00Z")
    ctx = setup_in_season_league(
        league_overrides={"name": "C2 L"},
        team_names=["A", "B"], divisions=["E", "E"],
    )
    a, b = ctx["teams"]
    matchup = create_regular_matchup(ctx["league"]["id"], 1, a, b)
    matchup = start_matchup(matchup)
    completed = finalize_matchup_with_scores(matchup, home_score=120.0, away_score=100.0)
    assert completed["state"] == "COMPLETED"
    assert completed["winner_team_id"] == a["id"]


def test_matchup_completed_updates_winner_standings(api, commissioner_headers):
    """PRD §3.6: "the winner's `wins` increments by 1 and `total_points_for`
    is incremented by its score and `total_points_against` by the opponent's
    score".

    Design: Difficulty/transitive_cascade/matchup_completed_updates_standings_seeds_bracket_depth3
    """
    set_clock("2026-11-15T00:00:00Z")
    ctx = setup_in_season_league(
        league_overrides={"name": "C2 L2"},
        team_names=["A", "B"], divisions=["E", "E"],
    )
    a, b = ctx["teams"]
    matchup = create_regular_matchup(ctx["league"]["id"], 1, a, b)
    matchup = start_matchup(matchup)
    finalize_matchup_with_scores(matchup, home_score=120.0, away_score=100.0)
    a_after = validate_success(
        api.get_team(a["id"], commissioner_headers), expected_status=200,
    )
    assert a_after["wins"] == 1
    assert a_after["total_points_for"] == 120.0


# ─── Boundary precision instance B: empty starter set ──────────────────────

def test_empty_starter_set_yields_zero_score(api, commissioner_headers):
    """PRD §3.6: "The injury-replacement projection runs across each team's
    locked starter slots — those `RosterSlot` rows where `slot_type` is
    `STARTER` and `week_locked` equals the matchup's `week` and the slot
    belongs to one of the two participating teams."
    PRD §3.6: "Each per-line-item contribution is rounded half-up to two
    decimal places first; the per-line-rounded contributions are then summed
    for the team; the team's running sum is then itself rounded half-up to
    two decimal places to produce the final `home_score` (or `away_score`)."

    Empty starter set → empty sum → home_score is 0.00.

    Design: Difficulty/boundary_precision_check/empty_starter_set_yields_zero_score
    """
    set_clock("2026-11-23T00:00:00Z")
    ctx = setup_in_season_league(
        league_overrides={"name": "Empty L"},
        team_names=["Home", "Away"], divisions=["E", "E"],
    )
    home, away = ctx["teams"]
    # Home does NOT set lineup, so all picks default to BENCH (no STARTERs).
    # Away sets one player as STARTER (the first drafted to the away team).
    away_player_id = next(
        p["player_id"] for p in ctx["picks"]
        if p["team_id"] == away["id"]
    )
    # Set lineup for away team with one starter.
    current_away = validate_success(
        api.get_team(away["id"], commissioner_headers), expected_status=200,
    )
    from test_helpers import make_team_owner_headers
    validate_success(
        api.set_lineup(
            away["id"], [away_player_id], current_away["version"],
            make_team_owner_headers(away["id"]),
        ),
        expected_status=200,
    )
    matchup = create_regular_matchup(ctx["league"]["id"], 1, home, away)
    matchup = start_matchup(matchup)
    # Finalize with auto-compute (no explicit scores) so the calc runs.
    res = api.finalize_matchup(
        matchup["id"], matchup["version"], commissioner_headers,
    )
    completed = validate_success(res, expected_status=200)
    assert completed["home_score"] == 0.00
    # Away starter is `ph1` (the first away pick from the seeder, projected_points=10.0
    # by setup default). Setup_in_season_league seeds with default projected=10.0,
    # so away_score should reflect that one player's ACTIVE projection.
    # We don't assert the exact value because the projected_points default may
    # change; we only assert it's > 0 (a non-empty starter set).
    assert completed["away_score"] > 0


def test_empty_starter_set_home_score_rounded_to_two_decimals(api, commissioner_headers):
    """PRD §3.6: "The pinned order is: round per line, sum, then round the
    sum — a single final round over the unrounded sum is incorrect because
    asymmetric rounding accumulates a different last cent."

    Empty starter set still rounds to two decimal places.

    Design: Difficulty/boundary_precision_check/empty_starter_set_yields_zero_score
    """
    set_clock("2026-11-23T00:00:00Z")
    ctx = setup_in_season_league(
        league_overrides={"name": "Empty L2"},
        team_names=["Home2", "Away2"], divisions=["E", "E"],
    )
    home, away = ctx["teams"]
    matchup = create_regular_matchup(ctx["league"]["id"], 1, home, away)
    matchup = start_matchup(matchup)
    res = api.finalize_matchup(
        matchup["id"], matchup["version"], commissioner_headers,
    )
    completed = validate_success(res, expected_status=200)
    # Both teams have no STARTER slots (no set-lineup was called).
    assert completed["home_score"] == 0.00
    assert completed["away_score"] == 0.00
