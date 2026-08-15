"""Rating formula variants, replay, and provisional-threshold claims (PRD §3.5, §3.6)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_player,
    get_player,
    report_and_confirm,
    run_meet,
    setup_one_club,
    setup_two_club_league,
    raise_dispute,
    open_review,
    resolve_dispute,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["federation_admin_headers"]

def _setup_rated_game(player_a_overrides, player_b_overrides, season_overrides=None,
                      result="WHITE_WIN"):
    """One meet, one board, host player (club A, white) vs away player (club B, black),
    reported by the host coach and confirmed by the away coach."""
    ctx = setup_two_club_league(
        season_overrides=season_overrides,
        players_a=[player_a_overrides],
        players_b=[player_b_overrides],
    )
    out = run_meet(
        ctx["season"]["id"], ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
        games=[(1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])],
        results=[result],
    )
    return ctx, out

def _events_for_player(api, player_id):
    events, _ = validate_paginated(api.list_rating_events(ADMIN, params={"player_id": player_id}))
    return events

def test_provisional_variant_running_average(api):
    """PRD §3.5: "When that count is below the season's `provisional_game_threshold`,
    the `PROVISIONAL` variant applies — a running average with no K-factor: the new
    rating is the player's pre-event rating multiplied by the games-before count, plus
    the opponent's snapshot rating, plus a 400-point swing scaled by twice the score
    minus one (so a win adds 400 points, a draw adds nothing, and a loss subtracts
    400), the whole sum divided by the games-before count plus one, and the quotient
    rounded half up to a whole number."

    Design: Difficulty/dual_variant_calc/provisional_vs_established_rating_divergence
    """
    ctx, out = _setup_rated_game({}, {"initial_rating": 1200, "initial_rated_games": 25},
                                 season_overrides={"provisional_game_threshold": 4,
                                                   "base_rating": 800})
    white = get_player(ctx["players_a"][0]["id"])
    # PROVISIONAL: (800*0 + 1200 + 400) / 1 = 1600 (ESTABLISHED would give 829)
    assert white["rating"] == 1600
    assert white["is_provisional"] is True

    events = _events_for_player(api, white["id"])
    assert len(events) == 1
    assert events[0]["formula_variant"] == "PROVISIONAL"
    assert events[0]["k_factor"] is None, "provisional events have no K"
    assert events[0]["rating_before"] == 800
    assert events[0]["rating_after"] == 1600

def test_established_variant_elo_tiered_k(api):
    """PRD §3.5: "When the games-before count is at least the threshold, the
    `ESTABLISHED` variant applies — an Elo expectation with a tiered K: the expected
    score is one divided by the quantity one plus ten raised to the power of the
    opponent's snapshot rating minus the player's pre-event rating, that difference
    divided by 400; K is 32 while the pre-event rating is below 2100, 24 while it is at
    least 2100 and below 2400, and 16 once it reaches 2400; and the new rating is the
    pre-event rating plus the round-half-up of K multiplied by the actual score minus
    the expected score."

    Design: Difficulty/dual_variant_calc/provisional_vs_established_rating_divergence
    """
    ctx, out = _setup_rated_game({}, {"initial_rating": 1200, "initial_rated_games": 25},
                                 season_overrides={"provisional_game_threshold": 4,
                                                   "base_rating": 800})
    black = get_player(ctx["players_b"][0]["id"])
    # ESTABLISHED: E = 1/(1+10^((800-1200)/400)) = 0.9091; delta = round(32*(0-0.9091)) = -29
    assert black["rating"] == 1171, "1200 - 29 via the ESTABLISHED variant"
    assert black["is_provisional"] is False
    assert black["rated_games_played"] == 26

    events = _events_for_player(api, black["id"])
    assert len(events) == 1
    assert events[0]["formula_variant"] == "ESTABLISHED"
    assert events[0]["k_factor"] == 32

def _setup_k_tier_boards():
    """Two boards: 2100-rated and 2099-rated host players, each vs an 800-rated visitor."""
    ctx = setup_two_club_league(
        season_overrides={"provisional_game_threshold": 4, "base_rating": 800},
        players_a=[{"initial_rating": 2100, "initial_rated_games": 25},
                   {"initial_rating": 2099, "initial_rated_games": 25}],
        players_b=[{"initial_rating": 800, "initial_rated_games": 30},
                   {"initial_rating": 800, "initial_rated_games": 30}],
    )
    out = run_meet(
        ctx["season"]["id"], ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
        games=[
            (1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"]),
            (1, 2, ctx["players_a"][1]["id"], ctx["players_b"][1]["id"]),
        ],
        results=["WHITE_WIN", "WHITE_WIN"],
    )
    return ctx, out

def test_k_factor_mid_tier_at_2100(api):
    """PRD §3.5: "K is 32 while the pre-event rating is below 2100, 24 while it is at
    least 2100 and below 2400, and 16 once it reaches 2400". A player at exactly 2100
    uses the mid tier.

    Design: Difficulty/combinatorial_formula/k_factor_tier_selection_boundary
    """
    ctx, _ = _setup_k_tier_boards()
    w_hi = ctx["players_a"][0]
    events = _events_for_player(api, w_hi["id"])
    assert len(events) == 1
    assert events[0]["k_factor"] == 24, "2100 uses the mid tier (at least 2100)"
    # delta rounds to 0: E(800 vs 2100) = 0.99944 -> round(24 * 0.00056) == 0
    assert get_player(w_hi["id"])["rating"] == 2100

def test_k_factor_low_tier_at_2099(api):
    """PRD §3.5: "K is 32 while the pre-event rating is below 2100, 24 while it is at
    least 2100 and below 2400, and 16 once it reaches 2400". A player at 2099 uses the
    low tier.

    Design: Difficulty/combinatorial_formula/k_factor_tier_selection_boundary
    """
    ctx, _ = _setup_k_tier_boards()
    w_lo = ctx["players_a"][1]
    events = _events_for_player(api, w_lo["id"])
    assert len(events) == 1
    assert events[0]["k_factor"] == 32, "2099 uses the low tier (below 2100)"
    assert get_player(w_lo["id"])["rating"] == 2099, "delta round(32 * 0.00056) == 0"

def test_rating_variant_switch_at_threshold(api):
    """PRD §3.5: "The update formula has two variants, selected per player per event."
    PRD §3.5: "Let the player's games-before count be their seeded
    `initial_rated_games` plus the count of their prior `EFFECTIVE` events."
    PRD §3.5: "the `opponent_rating_snapshot` — the opponent's rating frozen at the
    original confirmation, never recomputed afterward".

    Design: Corner/calculations/rating_variant_switch_at_threshold
    """
    ctx = setup_two_club_league(
        season_overrides={"provisional_game_threshold": 2, "base_rating": 800},
        players_a=[{"initial_rating": 1000, "initial_rated_games": 1}],
        players_b=[{"initial_rating": 800, "initial_rated_games": 30}],
    )
    run_meet(
        ctx["season"]["id"], ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
        games=[
            (1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"]),
            (2, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"]),
        ],
        results=["WHITE_WIN", "WHITE_WIN"],
    )
    w = ctx["players_a"][0]
    events = _events_for_player(api, w["id"])
    assert len(events) == 2
    by_before = {e["rating_before"]: e for e in events}
    # Game 1: n=1 < T=2 -> PROVISIONAL running average (1000*1 + 800 + 400)/2 = 1100
    first = by_before[1000]
    assert first["formula_variant"] == "PROVISIONAL"
    assert first["rating_after"] == 1100
    # Game 2: n=2 >= T=2 -> ESTABLISHED; snapshot froze the opponent at 792
    second = by_before[1100]
    assert second["formula_variant"] == "ESTABLISHED"
    assert second["k_factor"] == 32
    assert second["opponent_rating_snapshot"] == 792
    assert second["rating_after"] == 1105

    w_after = get_player(w["id"])
    assert w_after["rating"] == 1105
    assert w_after["rated_games_played"] == 3
    assert w_after["is_provisional"] is False
    # Loser: 800 -> 792 -> 787
    assert get_player(ctx["players_b"][0]["id"])["rating"] == 787

def test_rating_floor_clamp(api):
    """PRD §3.5: "Both variants clamp the outcome to the rating floor of 100 and the
    rating ceiling of 2900: a computed rating below the floor becomes 100, and one
    above the ceiling becomes 2900."

    Design: Corner/calculations/rating_floor_clamp
    """
    ctx, out = _setup_rated_game(
        {"initial_rating": 100, "initial_rated_games": 25},
        {"initial_rating": 800, "initial_rated_games": 30},
        season_overrides={"provisional_game_threshold": 4},
        result="BLACK_WIN",
    )
    loser = get_player(ctx["players_a"][0]["id"])
    # raw: 100 + round(32 * (0 - 0.01748)) = 100 - 1 = 99 -> clamped to the floor
    assert loser["rating"] == 100, "raw 99 clamps to the rating floor of 100"
    winner = get_player(ctx["players_b"][0]["id"])
    assert winner["rating"] == 801, "delta +1: round(32 * 0.01748) == 1"

def test_provisional_one_below_threshold(api):
    """PRD §3.5: "`is_provisional` reports whether the final count is still below the
    season's threshold."

    Design: Difficulty/boundary_precision_check/provisional_threshold_game_count
    """
    ctx = setup_one_club(season_overrides={"provisional_game_threshold": 4, "base_rating": 800})
    player = create_player(ctx["club"]["id"], full_name="P3",
                           initial_rating=1000, initial_rated_games=3)
    fetched = get_player(player["id"])
    assert fetched["rated_games_played"] == 3
    assert fetched["is_provisional"] is True, "3 < threshold 4 is provisional"

def test_provisional_exactly_at_threshold(api):
    """PRD §3.5: "`is_provisional` reports whether the final count is still below the
    season's threshold." Exactly at the threshold is no longer below it.

    Design: Difficulty/boundary_precision_check/provisional_threshold_game_count
    """
    ctx = setup_one_club(season_overrides={"provisional_game_threshold": 4, "base_rating": 800})
    player = create_player(ctx["club"]["id"], full_name="P4",
                           initial_rating=1000, initial_rated_games=4)
    fetched = get_player(player["id"])
    assert fetched["rated_games_played"] == 4
    assert fetched["is_provisional"] is False, "4 >= threshold 4 is not provisional"

def _setup_overturned_to_double_forfeit(api):
    """P (1000/25) beats Q (800/30), then the result is overturned to DOUBLE_FORFEIT."""
    ctx, out = _setup_rated_game(
        {"initial_rating": 1000, "initial_rated_games": 25},
        {"initial_rating": 800, "initial_rated_games": 30},
        season_overrides={"provisional_game_threshold": 4},
        result="WHITE_WIN",
    )
    pairing = out["pairings"][0]
    dispute = raise_dispute(pairing["id"], ctx["coach_b"]["id"],
                            reason="both players absent, result void")
    open_review(dispute["id"])
    resolve_dispute(dispute["id"], "OVERTURNED", resolved_result="DOUBLE_FORFEIT",
                    notes="game annulled")
    return ctx, pairing

def test_replay_restores_pre_confirm_ratings_after_void(api, federation_admin_headers):
    """PRD §3.6: "The overturn then cascades in a fixed order: first the pairing's
    result is replaced; second, if the pairing's `was_confirmed` is true, the two
    original rating events become `VOIDED`; third, each affected player is replayed per
    §3.5; fourth, if the new result is a played one, two fresh rating events are
    created with opponent snapshots taken *after* the void-replay, and both players are
    replayed again."
    PRD §3.4: "For a forfeit result (`WHITE_FORFEIT_WIN`, `BLACK_FORFEIT_WIN`, or
    `DOUBLE_FORFEIT`) no rating events exist at all".

    Design: Difficulty/compensating_invariant/rating_replay_restore_after_void
    """
    ctx, pairing = _setup_overturned_to_double_forfeit(api)
    p = get_player(ctx["players_a"][0]["id"])
    q = get_player(ctx["players_b"][0]["id"])
    assert p["rating"] == 1000, "replay restores exactly the pre-confirm rating"
    assert q["rating"] == 800
    assert p["rated_games_played"] == 25
    assert q["rated_games_played"] == 30
    assert p["performance_points"] == 0, "double forfeit scores nothing"
    assert q["performance_points"] == 0

    events, meta = validate_paginated(
        api.list_rating_events(federation_admin_headers, params={"pairing_id": pairing["id"]})
    )
    assert meta["total_count"] == 2
    assert all(e["status"] == "VOIDED" for e in events), "both original events voided"
    effective, eff_meta = validate_paginated(
        api.list_rating_events(federation_admin_headers,
                               params={"pairing_id": pairing["id"], "status": "EFFECTIVE"})
    )
    assert eff_meta["total_count"] == 0, "no effective events remain for the pairing"

def test_void_then_standings_forfeit_tallies(api, federation_admin_headers):
    """PRD §3.9: "Each side's `forfeit_losses` grow by one for every game it loses by
    forfeit, with a double forfeit charging both sides."
    PRD §3.9: "and a `DOUBLE_FORFEIT` gives neither side anything."

    Design: Difficulty/compensating_invariant/rating_replay_restore_after_void
    """
    ctx, pairing = _setup_overturned_to_double_forfeit(api)
    meet_id = pairing["meet_id"]
    validate_success(api.complete_meet(meet_id, federation_admin_headers))

    data = validate_success(api.get_standings(ctx["season"]["id"], federation_admin_headers))
    rows = {row["club_id"]: row for row in data["standings"]}
    host = rows[ctx["club_a"]["id"]]
    away = rows[ctx["club_b"]["id"]]
    assert host["game_points"] == 0 and away["game_points"] == 0
    assert host["forfeit_losses"] == 1 and away["forfeit_losses"] == 1
    assert host["match_points"] == 1 and away["match_points"] == 1, "0-0 is an exact tie"
