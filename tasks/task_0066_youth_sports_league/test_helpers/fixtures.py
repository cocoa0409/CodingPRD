"""Composite setup helpers.

Each test runs against a fresh, empty database (the harness restarts the server
before every test), so every fixture builds its preconditions from scratch using
only PRD-declared endpoints. Setup calls use get_success_data() so a setup
failure surfaces as a clear "Setup failed" rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_league_admin_headers,
    make_coach_headers,
    make_referee_headers,
)
from . import factories as f


ADMIN = make_league_admin_headers("admin-1")

# Phase order for the League lifecycle (PRD §2.8).
_PHASES = ["REGISTRATION", "EVALUATION", "DRAFT", "SEASON", "PLAYOFFS", "CLOSED"]


# ─────────────────────────────────────────────────────────────────────────────
# Primitive creators
# ─────────────────────────────────────────────────────────────────────────────

def create_league(draft_snake=None, **overrides):
    payload = f.create_league_payload(**overrides)
    if draft_snake is not None:
        payload["draft_snake"] = draft_snake
    return get_success_data(api_client.create_league(payload, ADMIN))


def set_clock(now_iso):
    return get_success_data(api_client.set_clock({"now_iso": now_iso}, ADMIN))


def create_division(league_id, **overrides):
    return get_success_data(
        api_client.create_division(
            f.create_division_payload(league_id, **overrides), ADMIN))


def create_family(league_id, **overrides):
    return get_success_data(
        api_client.create_family(
            f.create_family_payload(league_id, **overrides), ADMIN))


def create_team(league_id, division_id, **overrides):
    return get_success_data(
        api_client.create_team(
            f.create_team_payload(league_id, division_id, **overrides), ADMIN))


def create_field(league_id, **overrides):
    return get_success_data(
        api_client.create_field(
            f.create_field_payload(league_id, **overrides), ADMIN))


def create_referee(league_id, **overrides):
    return get_success_data(
        api_client.create_referee(
            f.create_referee_payload(league_id, **overrides), ADMIN))


def advance(league_id, target):
    return get_success_data(
        api_client.advance_league(league_id, {"target": target}, ADMIN))


def advance_to(league_id, target_phase):
    """Walk the League lifecycle forward to target_phase (PRD §2.8 order)."""
    out = None
    for phase in _PHASES:
        out = advance(league_id, phase)
        if phase == target_phase:
            break
    return out


def league_version(league_id):
    return get_success_data(api_client.get_league(league_id, ADMIN))["version"]


def game_version(game_id):
    return get_success_data(api_client.get_game(game_id, ADMIN))["version"]


# ─────────────────────────────────────────────────────────────────────────────
# Player progression
# ─────────────────────────────────────────────────────────────────────────────

def register_player(league_id, family_id, division_id, **overrides):
    return get_success_data(
        api_client.create_player(
            f.create_player_payload(league_id, family_id, division_id,
                                    **overrides), ADMIN))


def verify_age(player_id):
    return get_success_data(api_client.verify_age(player_id, ADMIN))


def evaluate_player(player_id, eval_speed=55, eval_hitting=55, eval_fielding=55):
    return get_success_data(api_client.evaluate_player(
        player_id,
        {"eval_speed": eval_speed, "eval_hitting": eval_hitting,
         "eval_fielding": eval_fielding},
        ADMIN))


def register_verified_evaluated_player(
        league_id, family_id, division_id, *, full_name="P", birth_date,
        birth_certificate_ref="bc",
        eval_speed=55, eval_hitting=55, eval_fielding=55):
    """Register a player and walk it (verify-age, evaluate) to EVALUATED.

    Caller must drive the league through REGISTRATION -> EVALUATION around the
    appropriate calls; this helper performs register (in REGISTRATION) then
    verify-age, and leaves evaluation to evaluate_players_after_eval_phase.
    """
    p = register_player(league_id, family_id, division_id,
                        full_name=full_name, birth_date=birth_date,
                        birth_certificate_ref=birth_certificate_ref)
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Draft-ready scenario: a league in DRAFT with N evaluated players + teams
# ─────────────────────────────────────────────────────────────────────────────

def setup_league_in_draft(*, num_teams=2, roster_cap=12, num_players=2,
                          draft_snake=True, clock_iso="2026-06-01T00:00:00Z"):
    """League advanced to DRAFT.

    Returns dict with keys: league, division, family, teams (list, slot order),
    players (list of EVALUATED players), league_version (current).

    Builds: league -> clock -> division -> teams(slots 1..N) -> family ->
    REGISTRATION -> register/verify N players -> EVALUATION -> evaluate all ->
    DRAFT.
    """
    league = create_league(draft_snake=draft_snake)
    if clock_iso:
        set_clock(clock_iso)
    division = create_division(league["id"], roster_cap=roster_cap)
    teams = []
    for i in range(num_teams):
        teams.append(create_team(
            league["id"], division["id"],
            name=chr(ord("X") + i), coach_user_id=f"c{i}", draft_slot=i + 1))
    family = create_family(league["id"], volunteer_deposit_cents=0)

    advance(league["id"], "REGISTRATION")
    players = []
    for i in range(num_players):
        p = register_player(
            league["id"], family["id"], division["id"],
            full_name=f"P{i + 1}",
            birth_date=f"2015-0{(i % 9) + 1}-15",
            birth_certificate_ref=f"bc{i + 1}")
        verify_age(p["id"])
        players.append(p)

    advance(league["id"], "EVALUATION")
    evaluated = []
    for p in players:
        evaluated.append(evaluate_player(p["id"]))

    league = advance(league["id"], "DRAFT")
    return {
        "league": league,
        "division": division,
        "family": family,
        "teams": teams,
        "players": evaluated,
        "league_version": league["version"],
    }


def draft_pick(league_id, team_id, player_id, expected_league_version,
               headers=None):
    """Record a draft pick. Returns the created DraftPick data."""
    return get_success_data(api_client.create_draft_pick(
        {"league_id": league_id, "team_id": team_id, "player_id": player_id,
         "expected_league_version": expected_league_version},
        headers or ADMIN))


# ─────────────────────────────────────────────────────────────────────────────
# Season scenario: a league in SEASON with teams, a field, a referee
# ─────────────────────────────────────────────────────────────────────────────

def setup_league_in_season(*, num_teams=2, num_fields=1, draft_snake=True,
                           max_games_per_day=10):
    """League advanced to SEASON with teams, field(s) and one referee.

    Returns dict: league, division, teams (slot order), fields (list),
    field (fields[0]), referee.
    """
    league = create_league(draft_snake=draft_snake)
    division = create_division(league["id"])
    teams = []
    for i in range(num_teams):
        teams.append(create_team(
            league["id"], division["id"],
            name=chr(ord("X") + i), coach_user_id=f"c{i}", draft_slot=i + 1))
    fields = []
    for i in range(num_fields):
        fields.append(create_field(
            league["id"], name=f"Field {i + 1}"))
    referee = create_referee(
        league["id"], user_id="ref-1", full_name="Ref One",
        max_games_per_day=max_games_per_day)

    advance_to(league["id"], "SEASON")
    return {
        "league": league,
        "division": division,
        "teams": teams,
        "fields": fields,
        "field": fields[0] if fields else None,
        "referee": referee,
    }


def schedule_game(league_id, division_id, home_team_id, away_team_id, field_id,
                  start_iso, end_iso, **overrides):
    return get_success_data(api_client.create_game(
        f.create_game_payload(league_id, division_id, home_team_id,
                              away_team_id, field_id, start_iso, end_iso,
                              **overrides), ADMIN))


def propose_assignment(game_id, referee_id, role="PLATE"):
    return get_success_data(api_client.create_assignment(
        f.create_assignment_payload(game_id, referee_id, role=role), ADMIN))


def confirm_assignment(assignment_id, referee_user_id="ref-1"):
    """Confirm an assignment as the owning referee (entity_backed ownership)."""
    return get_success_data(api_client.confirm_assignment(
        assignment_id, make_referee_headers(referee_user_id)))


def start_game(game_id):
    return get_success_data(api_client.start_game(game_id, ADMIN))


def finalize_game(game_id, home_runs, away_runs):
    return get_success_data(api_client.finalize_game(
        game_id, {"home_runs": home_runs, "away_runs": away_runs}, ADMIN))


def setup_game_with_confirmed_referee(*, draft_snake=True,
                                      start_iso="2026-05-01T17:00:00Z",
                                      end_iso="2026-05-01T19:00:00Z",
                                      max_games_per_day=10):
    """League in SEASON with one SCHEDULED game whose referee assignment is
    CONFIRMED. Returns dict: league, division, teams, field, referee, game,
    assignment.
    """
    s = setup_league_in_season(draft_snake=draft_snake,
                               max_games_per_day=max_games_per_day)
    game = schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        start_iso, end_iso)
    assignment = propose_assignment(game["id"], s["referee"]["id"])
    assignment = confirm_assignment(assignment["id"], s["referee"]["user_id"])
    s["game"] = game
    s["assignment"] = assignment
    return s


def setup_finalized_regular_game(*, draft_snake=True,
                                 home_runs=5, away_runs=2):
    """League in SEASON with one game taken all the way to FINAL.
    Returns dict from setup_game_with_confirmed_referee plus the finalized game.
    """
    s = setup_game_with_confirmed_referee(draft_snake=draft_snake)
    start_game(s["game"]["id"])
    s["game"] = finalize_game(s["game"]["id"], home_runs, away_runs)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Volunteer / family scenario
# ─────────────────────────────────────────────────────────────────────────────

def pledge_commitment(game_id, family_id, role, credit_cents):
    return get_success_data(api_client.create_volunteer_commitment(
        f.create_volunteer_commitment_payload(game_id, family_id, role,
                                               credit_cents), ADMIN))


def fulfill_commitment(commitment_id):
    return get_success_data(api_client.fulfill_commitment(commitment_id, ADMIN))
