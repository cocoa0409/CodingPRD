"""Dispute lifecycle, adjudication forks, and overturn cascades (PRD §3.5, §3.6, §3.9)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    finalize_season,
    finalize_standings,
    get_player,
    make_club_coach_headers,
    open_review,
    raise_dispute,
    report_and_confirm,
    report_result,
    resolve_dispute,
    run_meet,
    setup_two_club_league,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["federation_admin_headers"]

def _setup_two_board_disputes(api):
    """Board 1: R (900/25) beats S (700/30). Board 2: T (1000/25) beats U (800/30).
    Both pairings CONFIRMED, then both disputed by the away coach and moved to
    UNDER_REVIEW."""
    ctx = setup_two_club_league(
        season_overrides={"provisional_game_threshold": 4, "base_rating": 800},
        players_a=[{"initial_rating": 900, "initial_rated_games": 25},
                   {"initial_rating": 1000, "initial_rated_games": 25}],
        players_b=[{"initial_rating": 700, "initial_rated_games": 30},
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
    disputes = [
        raise_dispute(p["id"], ctx["coach_b"]["id"], reason="board result protest")
        for p in out["pairings"]
    ]
    for dispute in disputes:
        open_review(dispute["id"])
    return ctx, out, disputes

def test_upheld_branch_leaves_ratings_untouched(api, federation_admin_headers):
    """PRD §3.6: "For `UPHELD`, `resolved_result` must be absent — supplying one fails
    with `ERR_INVALID_REQUEST` — and the reported result stands: the pairing returns
    from `DISPUTED` to `CONFIRMED`, and if it had never been confirmed before the
    dispute, its rating side effects are applied now, exactly as on a first
    confirmation."

    Design: Difficulty/non_linear_state_machine/dispute_fork_divergent_side_effects
    """
    ctx, out, disputes = _setup_two_board_disputes(api)
    resolve_dispute(disputes[0]["id"], "UPHELD", notes="reported result stands")
    resolve_dispute(disputes[1]["id"], "OVERTURNED", resolved_result="DRAW",
                    notes="position was drawn by rule")

    # UPHELD branch: board 1 ratings are exactly the first-confirmation values.
    r = get_player(ctx["players_a"][0]["id"])
    s = get_player(ctx["players_b"][0]["id"])
    assert r["rating"] == 908, "900 + round(32 * (1 - 0.7597)) = 908, unchanged"
    assert s["rating"] == 692, "700 - 8, unchanged"
    assert r["performance_points"] == 3, "the win still counts"

    d1 = validate_success(api.get_dispute(disputes[0]["id"], federation_admin_headers))
    assert d1["status"] == "UPHELD"
    pairing1 = validate_success(api.get_pairing(out["pairings"][0]["id"], federation_admin_headers))
    assert pairing1["status"] == "CONFIRMED"
    assert pairing1["result"] == "WHITE_WIN"

def test_overturned_branch_rebases_both_players(api, federation_admin_headers):
    """PRD §3.6: "The overturn then cascades in a fixed order: first the pairing's
    result is replaced; second, if the pairing's `was_confirmed` is true, the two
    original rating events become `VOIDED`; third, each affected player is replayed per
    §3.5; fourth, if the new result is a played one, two fresh rating events are
    created with opponent snapshots taken *after* the void-replay, and both players are
    replayed again."

    Design: Difficulty/non_linear_state_machine/dispute_fork_divergent_side_effects
    """
    ctx, out, disputes = _setup_two_board_disputes(api)
    resolve_dispute(disputes[0]["id"], "UPHELD", notes="reported result stands")
    resolve_dispute(disputes[1]["id"], "OVERTURNED", resolved_result="DRAW",
                    notes="position was drawn by rule")

    # OVERTURNED branch: void 1008/792 -> replay to 1000/800 -> DRAW re-application
    # (T: round(32 * (0.5 - 0.7597)) = -8; U: round(32 * 0.2597) = +8).
    t = get_player(ctx["players_a"][1]["id"])
    u = get_player(ctx["players_b"][1]["id"])
    assert t["rating"] == 992
    assert u["rating"] == 808
    assert t["performance_points"] == 1, "draw scores one point"
    assert u["performance_points"] == 1

    d2 = validate_success(api.get_dispute(disputes[1]["id"], federation_admin_headers))
    assert d2["status"] == "OVERTURNED"
    pairing2 = validate_success(api.get_pairing(out["pairings"][1]["id"], federation_admin_headers))
    assert pairing2["status"] == "CONFIRMED"
    assert pairing2["result"] == "DRAW"

def _setup_overturned_to_black_win(api):
    """P (1000/25, host) beats Q (800/30), disputed, then overturned to BLACK_WIN."""
    ctx = setup_two_club_league(
        season_overrides={"provisional_game_threshold": 4, "base_rating": 800},
        players_a=[{"initial_rating": 1000, "initial_rated_games": 25}],
        players_b=[{"initial_rating": 800, "initial_rated_games": 30}],
    )
    out = run_meet(
        ctx["season"]["id"], ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
        games=[(1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])],
        results=["WHITE_WIN"],
    )
    pairing = out["pairings"][0]
    dispute = raise_dispute(pairing["id"], ctx["coach_b"]["id"],
                            reason="touch-move violation dispute")
    open_review(dispute["id"])
    return ctx, pairing, dispute

def test_overturn_cascade_replays_both_players(api, federation_admin_headers):
    """PRD §3.6: "The overturn then cascades in a fixed order: first the pairing's
    result is replaced; second, if the pairing's `was_confirmed` is true, the two
    original rating events become `VOIDED`; third, each affected player is replayed per
    §3.5; fourth, if the new result is a played one, two fresh rating events are
    created with opponent snapshots taken *after* the void-replay, and both players are
    replayed again."

    Design: Difficulty/transitive_cascade/dispute_overturn_rating_rebase_cascade
    """
    ctx, pairing, dispute = _setup_overturned_to_black_win(api)
    resolve_dispute(dispute["id"], "OVERTURNED", resolved_result="BLACK_WIN",
                    notes="result awarded to black")

    # Void back to 1000/800, then apply BLACK_WIN with post-void snapshots:
    # P: round(32 * (0 - 0.7597)) = -24 -> 976; Q: round(32 * 0.2403) = +24 -> 824.
    p = get_player(ctx["players_a"][0]["id"])
    q = get_player(ctx["players_b"][0]["id"])
    assert p["rating"] == 976
    assert q["rating"] == 824
    assert p["rated_games_played"] == 26, "exactly one effective event"
    assert q["rated_games_played"] == 31
    assert p["performance_points"] == 0
    assert q["performance_points"] == 3

def test_overturn_cascade_voids_and_reposts_events(api, federation_admin_headers):
    """PRD §3.6: "The overturn then cascades in a fixed order: first the pairing's
    result is replaced; second, if the pairing's `was_confirmed` is true, the two
    original rating events become `VOIDED`; third, each affected player is replayed per
    §3.5; fourth, if the new result is a played one, two fresh rating events are
    created with opponent snapshots taken *after* the void-replay, and both players are
    replayed again."
    PRD §3.5: "`peak_rating` is the maximum of the `initial_rating` and every effective
    event's `rating_after`".

    Design: Difficulty/transitive_cascade/dispute_overturn_rating_rebase_cascade
    """
    ctx, pairing, dispute = _setup_overturned_to_black_win(api)
    resolve_dispute(dispute["id"], "OVERTURNED", resolved_result="BLACK_WIN",
                    notes="result awarded to black")

    voided, voided_meta = validate_paginated(
        api.list_rating_events(ADMIN, params={"pairing_id": pairing["id"], "status": "VOIDED"})
    )
    assert voided_meta["total_count"] == 2, "both original events voided"
    effective, eff_meta = validate_paginated(
        api.list_rating_events(ADMIN, params={"pairing_id": pairing["id"], "status": "EFFECTIVE"})
    )
    assert eff_meta["total_count"] == 2, "two fresh events posted from the new result"

    p = get_player(ctx["players_a"][0]["id"])
    assert p["peak_rating"] == 1000, (
        "peak spans initial_rating and EFFECTIVE events only: the voided 1008 is excluded"
    )

def test_dispute_withdraw_restores_pairing(api, federation_admin_headers):
    """PRD §3.6: "Withdrawal moves the dispute to `WITHDRAWN` and restores the pairing
    without touching ratings: the pairing returns to `CONFIRMED` if its `was_confirmed`
    is true, and to `REPORTED` otherwise."

    Design: Corner/state_machines/dispute_withdraw_restores_pairing
    """
    ctx = setup_two_club_league(
        season_overrides={"provisional_game_threshold": 4},
        players_a=[{}], players_b=[{}],
    )
    out = run_meet(
        ctx["season"]["id"], ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
        games=[(1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])],
    )
    pairing = out["pairings"][0]
    report_result(pairing["id"], "WHITE_WIN", ctx["coach_a"]["id"])  # REPORTED, never confirmed
    dispute = raise_dispute(pairing["id"], ctx["coach_b"]["id"],
                            reason="score sheet mismatch found")

    withdrawn = validate_success(
        api.withdraw_dispute(dispute["id"], make_club_coach_headers(ctx["coach_b"]["id"]))
    )
    assert withdrawn["status"] == "WITHDRAWN"

    restored = validate_success(api.get_pairing(pairing["id"], federation_admin_headers))
    assert restored["status"] == "REPORTED", "never confirmed -> back to REPORTED"
    assert restored["was_confirmed"] is False
    events, meta = validate_paginated(
        api.list_rating_events(ADMIN, params={"pairing_id": pairing["id"]})
    )
    assert meta["total_count"] == 0, "withdrawal touches no ratings"

def test_resolve_open_dispute_rejected(api, federation_admin_headers):
    """PRD §3.6: "The administrator first opens review, moving the dispute from `OPEN`
    to `UNDER_REVIEW` (any other state fails with `ERR_DISPUTE_INVALID_STATE`), and
    then resolves it with an `outcome` of `UPHELD` or `OVERTURNED` plus optional
    `resolution_notes`."

    Design: Corner/errors/resolve_open_dispute_rejected
    """
    ctx = setup_two_club_league(
        season_overrides={"provisional_game_threshold": 4},
        players_a=[{}], players_b=[{}],
    )
    out = run_meet(
        ctx["season"]["id"], ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
        games=[(1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])],
    )
    pairing = out["pairings"][0]
    report_result(pairing["id"], "WHITE_WIN", ctx["coach_a"]["id"])
    dispute = raise_dispute(pairing["id"], ctx["coach_b"]["id"],
                            reason="score sheet mismatch found")

    res = api.resolve_dispute(dispute["id"], {"outcome": "UPHELD"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_DISPUTE_INVALID_STATE)

def test_season_complete_with_open_dispute_rejected(api, federation_admin_headers):
    """PRD §3.9: "The administrator completes a season only from `FINALIZING` — the
    state check comes first, with `ERR_SEASON_INVALID_STATE` — and two further
    conditions must hold in order: at least one standing snapshot must exist for the
    season (`ERR_STANDINGS_NOT_FINAL`), and no dispute in `OPEN` or `UNDER_REVIEW` may
    remain on pairings of the season's meets (`ERR_OPEN_DISPUTES_EXIST`)."

    Design: Corner/errors/season_complete_with_open_dispute_rejected
    """
    ctx = setup_two_club_league(
        season_overrides={"provisional_game_threshold": 4},
        players_a=[{}], players_b=[{}],
    )
    out = run_meet(
        ctx["season"]["id"], ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
        games=[(1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])],
        results=["WHITE_WIN"],
    )
    pairing = out["pairings"][0]
    raise_dispute(pairing["id"], ctx["coach_b"]["id"], reason="flag fall disagreement")

    finalize_season(ctx["season"]["id"])
    finalize_standings(ctx["season"]["id"])

    res = api.complete_season(ctx["season"]["id"], federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_OPEN_DISPUTES_EXIST)
    season = validate_success(api.get_season(ctx["season"]["id"], federation_admin_headers))
    assert season["status"] == "FINALIZING", "rejected completion leaves the season in place"
