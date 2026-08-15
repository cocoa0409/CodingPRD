"""Team standings computation and season close-out claims (PRD §2.7, §3.9)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_standing_row,
    confirm_pairing,
    create_active_season,
    create_club,
    create_coach,
    create_player,
    create_waived_membership,
    finalize_season,
    report_result,
    run_meet,
    setup_two_club_league,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["federation_admin_headers"]

def _standings(api, season_id):
    data = validate_success(api.get_standings(season_id, ADMIN))
    return data["standings"]

def test_standings_computed_read(api):
    """PRD §3.9: "The `sonneborn_berger` tiebreak sums, over the club's completed meets,
    the opponent's final season `match_points` multiplied by the club's own match
    result against that opponent (1 for a win, one half for a tie, 0 for a loss)."
    PRD §3.9: "The live standings read recomputes all of this on every call and returns
    it as a `standings` array."
    PRD §3.9: "Ranking follows a pinned cascade with no randomness: `match_points`
    descending".

    Design: Corner/endpoints/standings_computed_read
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    season_id = ctx["season"]["id"]
    # meet1: A (host) beats B
    run_meet(season_id, ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
             games=[(1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])],
             scheduled_date="2026-09-05", results=["WHITE_WIN"], complete=True)
    # meet2: B (host) vs A ends in a draw
    run_meet(season_id, ctx["club_b"], ctx["club_a"], ctx["coach_b"], ctx["coach_a"],
             games=[(1, 1, ctx["players_b"][0]["id"], ctx["players_a"][0]["id"])],
             scheduled_date="2026-09-12", results=["DRAW"], complete=True)

    table = _standings(api, season_id)
    assert len(table) == 2
    for row in table:
        assert_standing_row(row)
    first, second = table[0], table[1]
    assert first["club_id"] == ctx["club_a"]["id"], "match_points 3 > 1 decides at level 1"
    assert first["match_points"] == 3, "2 for the win + 1 for the draw"
    assert first["game_points"] == 1.5
    assert first["sonneborn_berger"] == 1.5, "B's final MP 1 x (1 + 0.5)"
    assert second["club_id"] == ctx["club_b"]["id"]
    assert second["match_points"] == 1
    assert second["game_points"] == 0.5
    assert second["sonneborn_berger"] == 1.5, "A's final MP 3 x (0 + 0.5)"

def test_standings_input_set_filtering(api):
    """PRD §3.9: "For each club of a season, over meets with status `COMPLETED` only,
    board points accrue per `CONFIRMED` pairing". An IN_PROGRESS meet contributes
    nothing yet, even with a confirmed board.

    Design: Corner/calculations/standings_input_set_filtering
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    season_id = ctx["season"]["id"]
    club_c = create_club(season_id, name="Gamma", school_name="Gamma HS")
    coach_c = create_coach(club_c["id"], full_name="Coach C", email="coach.c@example.com")
    pc = create_player(club_c["id"], full_name="PC")
    create_waived_membership(pc["id"], season_id)

    # meet1: A (host) beats B -> COMPLETED
    run_meet(season_id, ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
             games=[(1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])],
             scheduled_date="2026-09-05", results=["WHITE_WIN"], complete=True)
    # meet2: A (host) vs C -> IN_PROGRESS with a CONFIRMED board
    out2 = run_meet(season_id, ctx["club_a"], club_c, ctx["coach_a"], coach_c,
                    games=[(1, 1, ctx["players_a"][0]["id"], pc["id"])],
                    scheduled_date="2026-09-12")
    report_result(out2["pairings"][0]["id"], "WHITE_WIN", ctx["coach_a"]["id"])
    confirm_pairing(out2["pairings"][0]["id"], coach_c["id"])

    table = {row["club_id"]: row for row in _standings(api, season_id)}
    assert table[ctx["club_a"]["id"]]["match_points"] == 2, "only the COMPLETED meet counts"
    assert table[ctx["club_a"]["id"]]["game_points"] == 1
    assert table[ctx["club_b"]["id"]]["match_points"] == 0
    assert table[club_c["id"]]["match_points"] == 0, "meet2 excluded while IN_PROGRESS"
    assert table[club_c["id"]]["game_points"] == 0

def test_standings_tiebreak_created_at(api):
    """PRD §3.9: "Ranking follows a pinned cascade with no randomness: `match_points`
    descending; then head-to-head match points descending, applied only when exactly
    two clubs are tied on match points and skipped — contributing nothing — for larger
    tied groups; then `sonneborn_berger` descending; then `game_points` descending;
    then `forfeit_losses` ascending; and finally the club's `created_at` ascending, so
    the earlier-registered club ranks higher — ids are never used as a tiebreak."

    Design: Corner/calculations/standings_tiebreak_created_at
    """
    ctx = setup_two_club_league(players_a=[{}], players_b=[{}])
    season_id = ctx["season"]["id"]
    # Two mutual draws: every metric ties (MP 2, GP 1.0, SB 2.0, forfeit_losses 0).
    run_meet(season_id, ctx["club_a"], ctx["club_b"], ctx["coach_a"], ctx["coach_b"],
             games=[(1, 1, ctx["players_a"][0]["id"], ctx["players_b"][0]["id"])],
             scheduled_date="2026-09-05", results=["DRAW"], complete=True)
    run_meet(season_id, ctx["club_b"], ctx["club_a"], ctx["coach_b"], ctx["coach_a"],
             games=[(1, 1, ctx["players_b"][0]["id"], ctx["players_a"][0]["id"])],
             scheduled_date="2026-09-12", results=["DRAW"], complete=True)

    table = _standings(api, season_id)
    assert len(table) == 2
    for row in table:
        assert row["match_points"] == 2
        assert row["game_points"] == 1.0
        assert row["sonneborn_berger"] == 2.0
        assert row["forfeit_losses"] == 0
    assert table[0]["club_id"] == ctx["club_a"]["id"], "created earlier -> ranks higher"
    assert table[1]["club_id"] == ctx["club_b"]["id"]

def test_season_complete_without_standings_rejected(api, federation_admin_headers):
    """PRD §3.9: "The administrator completes a season only from `FINALIZING` — the
    state check comes first, with `ERR_SEASON_INVALID_STATE` — and two further
    conditions must hold in order: at least one standing snapshot must exist for the
    season (`ERR_STANDINGS_NOT_FINAL`), and no dispute in `OPEN` or `UNDER_REVIEW` may
    remain on pairings of the season's meets (`ERR_OPEN_DISPUTES_EXIST`)."

    Design: Corner/errors/season_complete_without_standings_rejected
    """
    season = create_active_season()
    finalize_season(season["id"])
    res = api.complete_season(season["id"], federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_STANDINGS_NOT_FINAL)

def test_occ_standings_stale_season_version(api, federation_admin_headers):
    """PRD §2.7: "Finalizing a season's standings requires `expected_season_version`
    matching the season's current `version`. Finalizing replaces the prior snapshot set
    and may be repeated legitimately while the season is being closed; a finalize whose
    `expected_season_version` no longer matches because a prior finalize advanced the
    season is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_standings_stale_season_version
    """
    season = create_active_season()
    create_club(season["id"], name="Alpha")
    finalize_season(season["id"])
    fresh = validate_success(api.get_season(season["id"], federation_admin_headers))

    snapshots = validate_success(
        api.finalize_standings(season["id"],
                               {"expected_season_version": fresh["version"]},
                               federation_admin_headers),
        201,
    )
    assert len(snapshots) == 1, "one snapshot per club"
    assert snapshots[0]["club_id"]
    assert snapshots[0]["is_final"] is True

    res = api.finalize_standings(season["id"],
                                 {"expected_season_version": fresh["version"]},
                                 federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    assert res.status_code == 412
