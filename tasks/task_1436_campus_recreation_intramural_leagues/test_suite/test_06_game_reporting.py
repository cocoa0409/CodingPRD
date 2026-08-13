"""Score-report fork/join, disputes, finalize gating, and forfeit target
validation (PRD §3.4)."""
import pytest

from test_helpers import (
    COORDINATOR,
    REC_ADMIN,
    ApiErrorId,
    api_client,
    create_finalize_payload,
    create_score_report_payload,
    finalize_game,
    make_member_headers,
    season_game_context,
    set_clock,
    validate_error,
    validate_success,
)


def test_first_report_forks_to_played_pending_confirm():
    """PRD §3.4: "The first report moves the game `SCHEDULED →
    PLAYED_PENDING_CONFIRM` and stores it as `report_home` or `report_away`
    according to the reporting side."

    Design: Difficulty/non_linear_state_machine/game_score_fork_join_dispute
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context()
    set_clock("2026-09-08T20:00:00Z")
    data = validate_success(api_client.submit_score_report(
        ctx["game"]["id"],
        create_score_report_payload("HOME", 2, 1, 4),
        make_member_headers(ctx["captains"][0]["id"]),
    ), 201)
    assert data["status"] == "PLAYED_PENDING_CONFIRM"
    assert data["report_home"] is not None
    assert data["report_home"]["home_score"] == 2
    assert data["report_home"]["away_score"] == 1
    assert data["report_home"]["opponent_sportsmanship"] == 4
    assert data["report_away"] is None


def test_mismatched_second_report_disputes_then_finalize():
    """PRD §3.4: "A second report from the opposing side whose scores do *not*
    exactly match moves the game `PLAYED_PENDING_CONFIRM → DISPUTED`; both
    reports are kept, and no standings or sportsmanship effects apply yet."
    PRD §3.4: "A `RecAdmin` resolves any `PLAYED_PENDING_CONFIRM` or
    `DISPUTED` game through finalization, supplying authoritative
    `home_score`, `away_score`, `home_sportsmanship`, `away_sportsmanship`,
    and `actual_duration_minutes`. Finalization moves the game to `FINAL`
    using the coordinator-supplied scores; the home team is credited the
    finalize call's `home_sportsmanship` and the away team its
    `away_sportsmanship` as received ratings; and `actual_duration_minutes` is
    recorded, where it will drive final official pay per §3.6."
    PRD §3.4: "The **result effects** of a game reaching `FINAL` are: the
    higher-scored team's `wins` increments by 1 and its `points` by 3; the
    loser's `losses` increments by 1; on equal scores — possible only in the
    `REGULAR` round — both teams' `ties` increment by 1 and both gain 1
    `points`."

    Design: Difficulty/non_linear_state_machine/game_score_fork_join_dispute
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context()
    set_clock("2026-09-08T20:00:00Z")
    game_id = ctx["game"]["id"]
    validate_success(api_client.submit_score_report(
        game_id, create_score_report_payload("HOME", 2, 1, 4),
        make_member_headers(ctx["captains"][0]["id"]),
    ), 201)
    disputed = validate_success(api_client.submit_score_report(
        game_id, create_score_report_payload("AWAY", 2, 2, 5),
        make_member_headers(ctx["captains"][1]["id"]),
    ), 201)
    assert disputed["status"] == "DISPUTED"
    assert disputed["report_home"] is not None
    assert disputed["report_away"] is not None
    # No standings or sportsmanship effects on the divergent branch.
    home_mid = validate_success(api_client.get_team(
        ctx["teams"][0]["id"], REC_ADMIN))
    away_mid = validate_success(api_client.get_team(
        ctx["teams"][1]["id"], REC_ADMIN))
    assert home_mid["points"] == 0 and home_mid["wins"] == 0
    assert home_mid["sportsmanship_rating"] is None
    assert away_mid["points"] == 0 and away_mid["losses"] == 0
    assert away_mid["sportsmanship_rating"] is None

    final = finalize_game(game_id, 2, 1, 4, 5, 90)
    assert final["status"] == "FINAL"
    assert final["final_home_score"] == 2
    assert final["final_away_score"] == 1
    home = validate_success(api_client.get_team(
        ctx["teams"][0]["id"], REC_ADMIN))
    away = validate_success(api_client.get_team(
        ctx["teams"][1]["id"], REC_ADMIN))
    assert home["wins"] == 1 and home["points"] == 3
    assert home["sportsmanship_rating"] == pytest.approx(4.00)
    assert away["losses"] == 1 and away["points"] == 0
    assert away["sportsmanship_rating"] == pytest.approx(5.00)


def test_game_report_before_start_returns_not_reportable():
    """PRD §3.4: "Reporting before the game's start is rejected with
    `ERR_GAME_NOT_REPORTABLE` (HTTP 409); a caller who is not the captain of
    the reported side's team is `ERR_FORBIDDEN`."

    Design: Corner/state_machines/game_report_before_start_returns_not_reportable
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context()
    set_clock("2026-09-08T17:59:00Z")  # one minute before the 18:00 start
    resp = api_client.submit_score_report(
        ctx["game"]["id"], create_score_report_payload("HOME", 2, 1, 4),
        make_member_headers(ctx["captains"][0]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_GAME_NOT_REPORTABLE)
    game = validate_success(api_client.get_game(
        ctx["game"]["id"], REC_ADMIN))
    assert game["status"] == "SCHEDULED"
    assert game["report_home"] is None


def test_game_duplicate_report_same_side_returns_error():
    """PRD §3.4: "A second report from the *same* side is rejected with
    `ERR_DUPLICATE_SCORE_REPORT`."

    Design: Corner/state_machines/game_duplicate_report_same_side_returns_error
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context()
    set_clock("2026-09-08T20:00:00Z")
    validate_success(api_client.submit_score_report(
        ctx["game"]["id"], create_score_report_payload("HOME", 2, 1, 4),
        make_member_headers(ctx["captains"][0]["id"]),
    ), 201)
    resp = api_client.submit_score_report(
        ctx["game"]["id"], create_score_report_payload("HOME", 2, 1, 4),
        make_member_headers(ctx["captains"][0]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCORE_REPORT)
    game = validate_success(api_client.get_game(
        ctx["game"]["id"], REC_ADMIN))
    assert game["status"] == "PLAYED_PENDING_CONFIRM"
    assert game["report_home"] is not None
    assert game["report_away"] is None


def test_game_finalize_from_scheduled_returns_invalid_state():
    """PRD §3.4: "A `RecAdmin` resolves any `PLAYED_PENDING_CONFIRM` or
    `DISPUTED` game through finalization, supplying authoritative
    `home_score`, `away_score`, `home_sportsmanship`, `away_sportsmanship`,
    and `actual_duration_minutes`."
    PRD §5: `ERR_INVALID_STATE` (HTTP 409) — the generic illegal
    transition/state precondition.

    Design: Corner/state_machines/game_finalize_from_scheduled_returns_invalid_state
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context()
    set_clock("2026-09-08T20:00:00Z")
    resp = api_client.finalize_game(
        ctx["game"]["id"], create_finalize_payload(2, 1, 4, 5, 90),
        REC_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    game = validate_success(api_client.get_game(
        ctx["game"]["id"], REC_ADMIN))
    assert game["status"] == "SCHEDULED"
    assert game["final_home_score"] is None


def test_declare_forfeit_wrong_team_returns_error():
    """PRD §3.4: "A game-time forfeit may be declared by a
    `LeagueCoordinator` from `SCHEDULED` or `RESCHEDULE_REQUIRED` — including
    playoff shells — once the logical clock has reached `start_at` (earlier
    attempts are `ERR_GAME_NOT_REPORTABLE`), supplying a `forfeiting_team_id`
    that must be either the home or the away team (otherwise
    `ERR_FORFEITING_TEAM_INVALID`, HTTP 422)."

    Design: Corner/state_machines/declare_forfeit_wrong_team_returns_error
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context(num_teams=3, min_teams=3)
    third = ctx["teams"][2]
    set_clock("2026-09-08T18:30:00Z")
    resp = api_client.declare_forfeit(
        ctx["game"]["id"], {"forfeiting_team_id": third["id"]}, COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_FORFEITING_TEAM_INVALID)
    game = validate_success(api_client.get_game(
        ctx["game"]["id"], REC_ADMIN))
    assert game["status"] == "SCHEDULED"
    home = validate_success(api_client.get_team(
        ctx["teams"][0]["id"], REC_ADMIN))
    away = validate_success(api_client.get_team(
        ctx["teams"][1]["id"], REC_ADMIN))
    assert home["forfeit_count"] == 0 and home["losses"] == 0
    assert away["forfeit_count"] == 0 and away["wins"] == 0
