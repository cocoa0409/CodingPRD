"""Game's parallel schedule_status x score_status dimensions: forfeit, score
confirmation, and invalid-state guards.

Covers non_linear_state_machine (parallel dimensions) plus the confirm-score
invalid-state corner.
"""
from test_helpers import (
    validate_success, validate_error,
    make_league_admin_headers, make_referee_headers, make_team_captain_headers,
    ApiErrorId,
)
import test_helpers.fixtures as fx

ADMIN = make_league_admin_headers()


def test_forfeit_drives_both_dimensions_in_one_step(api):
    """PRD §3.7: "The forfeit moves `schedule_status` to the terminal `FORFEITED` and
    `score_status` to `CONFIRMED` in one step, records the charged team in
    `forfeiting_team_id` ..., credits the non-forfeiting team with a forfeit win and
    the forfeiting team with a loss, recomputes standings for both teams ..."

    Design: Difficulty/non_linear_state_machine/game_parallel_schedule_x_score_dimensions
    """
    s = fx.setup_scheduled_game(with_head_referee=False)
    game = s["game"]
    forfeited = validate_success(
        api.forfeit_game(game["id"], {"forfeiting_team_id": s["away_team"]["id"]}, ADMIN)
    )
    assert forfeited["schedule_status"] == "FORFEITED"
    assert forfeited["score_status"] == "CONFIRMED"


def test_forfeit_awards_three_nil_win_and_loss(api):
    """PRD §3.8: "A forfeited game contributes a win to the non-forfeiting team scored
    as three to nothing and a loss to the forfeiting team."

    Design: Difficulty/non_linear_state_machine/game_parallel_schedule_x_score_dimensions
    """
    s = fx.setup_scheduled_game(with_head_referee=False)
    validate_success(
        api.forfeit_game(s["game"]["id"], {"forfeiting_team_id": s["away_team"]["id"]}, ADMIN)
    )
    home = validate_success(api.get_team(s["home_team"]["id"], ADMIN))
    away = validate_success(api.get_team(s["away_team"]["id"], ADMIN))
    assert home["points"] == 3 and home["wins"] == 1, (
        f"non-forfeiting team should have a forfeit win (3 pts), got {home['points']}/{home['wins']}"
    )
    assert away["losses"] == 1, f"forfeiting team should take a loss, got {away['losses']}"


def test_confirm_score_flips_schedule_to_played(api):
    """PRD §3.7: "Confirmation advances `score_status` from `SUBMITTED` to `CONFIRMED`
    and, as a cross-dimension cascade, flips the game's `schedule_status` to the
    terminal `PLAYED`, releases the game's referee assignments to `RELEASED`, and
    recomputes standings for both teams."

    Design: Difficulty/non_linear_state_machine/game_parallel_schedule_x_score_dimensions
    """
    s = fx.setup_in_play_game_pending()
    confirmed = fx.submit_and_confirm_score(s["game"]["id"], s["referee"]["id"], 2, 1)
    assert confirmed["score_status"] == "CONFIRMED"
    assert confirmed["schedule_status"] == "PLAYED"


def test_confirm_score_while_pending_rejected(api):
    """PRD §3.7: "The assigned head referee confirms a submitted score, which requires
    that a `HEAD` referee assignment in `ASSIGNED` state exists for the game and that
    the acting referee is that assignment's referee."
    PRD §2.7: "then the target resource's state validity for the requested transition
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/confirm_score_from_pending_returns_invalid_state
    """
    s = fx.setup_in_play_game_pending()
    ref_headers = make_referee_headers(s["referee"]["id"])
    resp = api.confirm_score(s["game"]["id"], ref_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
