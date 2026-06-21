"""Game scheduling, rainout/reschedule cycle, forfeit, finalize, field overlap.

Covers: non_linear_state_machine (rainout->reschedule cycle), transitive_cascade
(rainout releases assignment), resource_temporal_overlap (field buffer),
corner state_machines (rainout-from-FINAL invalid, playoff finalize eliminates),
corner errors (stale game version, tie not allowed), cross_cutting
(forfeit cascade).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_league_admin_headers,
)
from test_helpers import fixtures as fx


ADMIN = make_league_admin_headers("admin-1")


# ─────────────────────────────────────────────────────────────────────────────
# non_linear_state_machine / game_rainout_reschedule_cycle  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_rainout_reschedule_cycle_returns_scheduled(api):
    """PRD §3.6: "A successful reschedule updates `start_iso` and `end_iso` to
    the makeup slot, raises `rainout_count` by 1, and increments the game's
    `version`. This SCHEDULED → RAINED_OUT → SCHEDULED cycle is what makes the
    game lifecycle cyclic."

    Design: Difficulty/non_linear_state_machine/game_rainout_reschedule_cycle
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=1)
    game = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")
    rained = validate_success(api.rainout_game(game["id"], ADMIN))
    gv = rained["version"]

    out = validate_success(api.reschedule_game(game["id"], {
        "start_iso": "2026-05-08T17:00:00Z",
        "end_iso": "2026-05-08T19:00:00Z",
        "expected_game_version": gv,
    }, ADMIN))
    assert out["status"] == "SCHEDULED", out["status"]
    assert out["rainout_count"] == 1, out["rainout_count"]
    assert out["start_iso"] == "2026-05-08T17:00:00Z", out["start_iso"]


def test_rainout_sets_status_rained_out(api):
    """PRD §3.6: "a `LeagueAdmin` rains out a `SCHEDULED` game while the league is
    in `SEASON` or `PLAYOFFS`, moving it to `RAINED_OUT`."

    Design: Difficulty/non_linear_state_machine/game_rainout_reschedule_cycle
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=1)
    game = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")
    out = validate_success(api.rainout_game(game["id"], ADMIN))
    assert out["status"] == "RAINED_OUT", out["status"]


# ─────────────────────────────────────────────────────────────────────────────
# transitive_cascade / rainout_cascades_game_to_assignment_release_depth2  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_rainout_releases_confirmed_assignment(api):
    """PRD §3.6: "The rainout releases the umpires: every `PROPOSED` or
    `CONFIRMED` referee assignment on the game transitions to `RELEASED` (each
    released assignment increments its own `version`)."

    Link 1 (game RAINED_OUT) -> link 2 (assignment RELEASED).

    Design: Difficulty/transitive_cascade/rainout_cascades_game_to_assignment_release_depth2
    """
    s = fx.setup_game_with_confirmed_referee()
    out = validate_success(api.rainout_game(s["game"]["id"], ADMIN))
    assert out["status"] == "RAINED_OUT", out["status"]              # link 1

    assignment = validate_success(api.get_assignment(s["assignment"]["id"], ADMIN))
    assert assignment["status"] == "RELEASED", assignment["status"]  # link 2


def test_rainout_keeps_game_rained_out_after_release(api):
    """PRD §3.6: "every `PROPOSED` or `CONFIRMED` referee assignment on the game
    transitions to `RELEASED`".

    Design: Difficulty/transitive_cascade/rainout_cascades_game_to_assignment_release_depth2
    """
    s = fx.setup_game_with_confirmed_referee()
    validate_success(api.rainout_game(s["game"]["id"], ADMIN))
    assignment = validate_success(api.get_assignment(s["assignment"]["id"], ADMIN))
    assert assignment["status"] == "RELEASED", assignment["status"]
    game = validate_success(api.get_game(s["game"]["id"], ADMIN))
    assert game["status"] == "RAINED_OUT", game["status"]


# ─────────────────────────────────────────────────────────────────────────────
# resource_temporal_overlap / field_slot_overlap_with_buffer  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_field_slot_conflict_within_buffer(api):
    """PRD §3.5: "Treat each existing non-terminal game on the same field as
    occupying a buffered window: subtract the field's `turnover_buffer_minutes`
    from its start and add the same buffer to its end. The new game `[start_iso,
    end_iso)` conflicts with such an existing game when the new start falls before
    the existing game's buffered end and the existing game's buffered start falls
    before the new end".

    Existing 17:00-19:00 + 30m buffer blocks through 19:30; a 19:15 start collides.

    Design: Difficulty/resource_temporal_overlap/field_slot_overlap_with_buffer
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=1)
    fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")

    resp = api.create_game({
        "league_id": s["league"]["id"], "division_id": s["division"]["id"],
        "home_team_id": s["teams"][0]["id"], "away_team_id": s["teams"][1]["id"],
        "field_id": s["field"]["id"],
        "start_iso": "2026-05-01T19:15:00Z", "end_iso": "2026-05-01T21:00:00Z",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FIELD_SLOT_CONFLICT.value)


def test_field_slot_no_conflict_at_buffer_boundary(api):
    """PRD §3.5: "A touch exactly at a buffered boundary does not conflict (the
    comparison is strict)."

    Existing 17:00-19:00 + 30m buffer ends at 19:30; a new game starting at
    exactly 19:30 touches the buffered boundary and is allowed.

    Design: Difficulty/resource_temporal_overlap/field_slot_overlap_with_buffer
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=1)
    fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")

    out = validate_success(api.create_game({
        "league_id": s["league"]["id"], "division_id": s["division"]["id"],
        "home_team_id": s["teams"][0]["id"], "away_team_id": s["teams"][1]["id"],
        "field_id": s["field"]["id"],
        "start_iso": "2026-05-01T19:30:00Z", "end_iso": "2026-05-01T21:00:00Z",
    }, ADMIN), 201)
    assert out["status"] == "SCHEDULED", out["status"]


# ─────────────────────────────────────────────────────────────────────────────
# corner: errors / stale_game_version_on_reschedule  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_stale_game_version_on_second_reschedule(api):
    """PRD §2.11: "The reschedule request must carry `expected_game_version`, the
    `version` of the target `Game` that the client last observed. If the game's
    `version` has advanced since the client read it — for instance because an
    earlier reschedule already moved it — the request is rejected with
    `ERR_STALE_GAME_VERSION` (HTTP 412), so the writer re-reads rather than
    overwriting the newer slot."

    Design: Corner/errors/stale_game_version_on_reschedule
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=1)
    game = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")

    rained = validate_success(api.rainout_game(game["id"], ADMIN))
    gv0 = rained["version"]
    validate_success(api.reschedule_game(game["id"], {
        "start_iso": "2026-05-08T17:00:00Z", "end_iso": "2026-05-08T19:00:00Z",
        "expected_game_version": gv0,
    }, ADMIN))
    validate_success(api.rainout_game(game["id"], ADMIN))

    resp = api.reschedule_game(game["id"], {
        "start_iso": "2026-05-15T17:00:00Z", "end_iso": "2026-05-15T19:00:00Z",
        "expected_game_version": gv0,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_GAME_VERSION.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: validations / tie_not_allowed_on_finalize  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_tie_not_allowed_on_finalize(api):
    """PRD §3.5: "Both run totals must be provided and non-negative, and they must
    differ — ties are not allowed and equal scores are rejected with
    `ERR_TIE_NOT_ALLOWED`."

    Design: Corner/validations/tie_not_allowed_on_finalize
    """
    s = fx.setup_game_with_confirmed_referee()
    fx.start_game(s["game"]["id"])
    resp = api.finalize_game(s["game"]["id"], {"home_runs": 4, "away_runs": 4}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_TIE_NOT_ALLOWED.value)
    game = validate_success(api.get_game(s["game"]["id"], ADMIN))
    assert game["status"] == "IN_PROGRESS", game["status"]


# ─────────────────────────────────────────────────────────────────────────────
# corner: state_machines / rainout_from_final_is_invalid  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_rainout_from_final_is_invalid(api):
    """PRD §2.8: "an operation attempted in the wrong league phase is rejected
    with `ERR_INVALID_STATE`." §3.6: "a `LeagueAdmin` rains out a `SCHEDULED`
    game". A FINAL game is not SCHEDULED, so rainout is rejected with
    `ERR_INVALID_STATE`.

    Design: Corner/state_machines/rainout_from_final_is_invalid
    """
    s = fx.setup_finalized_regular_game(home_runs=5, away_runs=2)
    resp = api.rainout_game(s["game"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─────────────────────────────────────────────────────────────────────────────
# corner: state_machines / finalize_advances_playoff_eliminates_loser  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_finalize_playoff_sets_winner_and_standings(api):
    """PRD §3.5: "Finalizing sets `winner_team_id` to the team with more runs and
    updates both teams' standings: the winner's `wins` and the loser's `losses`
    each rise by 1". §3.5: "If the game is a `PLAYOFF` game, the losing team is
    eliminated".

    Design: Corner/state_machines/finalize_advances_playoff_eliminates_loser
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=1)
    fx.advance(s["league"]["id"], "PLAYOFFS")
    game = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-06-01T17:00:00Z", "2026-06-01T19:00:00Z",
        game_type="PLAYOFF", playoff_round=1)
    a = fx.propose_assignment(game["id"], s["referee"]["id"])
    fx.confirm_assignment(a["id"], s["referee"]["user_id"])
    fx.start_game(game["id"])

    out = validate_success(api.finalize_game(
        game["id"], {"home_runs": 8, "away_runs": 3}, ADMIN))
    assert out["status"] == "FINAL", out["status"]
    assert out["winner_team_id"] == s["teams"][0]["id"], out["winner_team_id"]

    tx = validate_success(api.get_team(s["teams"][0]["id"], ADMIN))
    ty = validate_success(api.get_team(s["teams"][1]["id"], ADMIN))
    assert tx["wins"] == 1, tx["wins"]
    assert ty["losses"] == 1, ty["losses"]


# ─────────────────────────────────────────────────────────────────────────────
# cross_cutting / forfeit_cascades_release_assignments  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_forfeit_cascades_release_and_awards_win(api):
    """PRD §3.6: "The forfeit sets `winner_team_id` to the non-forfeiting team and
    adjusts standings — the non-forfeiting team gains a win and the forfeiting
    team a loss — while `run_differential` is left unchanged. As with a rainout,
    every non-terminal referee assignment on the game transitions to `RELEASED`."

    Design: Corner/cross_cutting_complexity_layers/forfeit_cascades_release_assignments
    """
    s = fx.setup_game_with_confirmed_referee()
    out = validate_success(api.forfeit_game(
        s["game"]["id"], {"forfeiting_team_id": s["teams"][0]["id"]}, ADMIN))
    assert out["status"] == "FORFEITED", out["status"]
    assert out["winner_team_id"] == s["teams"][1]["id"], out["winner_team_id"]

    assignment = validate_success(api.get_assignment(s["assignment"]["id"], ADMIN))
    assert assignment["status"] == "RELEASED", assignment["status"]
    tx = validate_success(api.get_team(s["teams"][0]["id"], ADMIN))
    ty = validate_success(api.get_team(s["teams"][1]["id"], ADMIN))
    assert ty["wins"] == 1, ty["wins"]
    assert tx["losses"] == 1, tx["losses"]
