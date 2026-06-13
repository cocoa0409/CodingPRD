"""Composite setup helpers.

These encapsulate the multi-step API preambles the design instances require, so
tests focus on assertions. Each test runs against a fresh empty database (the runner
restarts the server before every test), so every helper builds its preconditions from
scratch using only PRD-declared endpoints.

All helpers use get_success_data() (lenient 2xx validator) so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: TeamCaptain is entity_backed:Player and Referee is
entity_backed:Referee. Any ownership-gated call uses make_team_captain_headers(player_id)
or make_referee_headers(referee_id) with the real entity id — never a shared constant.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import (
    make_league_admin_headers, make_conduct_officer_headers,
    make_team_captain_headers, make_referee_headers,
)
from . import factories as F


ADMIN = make_league_admin_headers()
OFFICER = make_conduct_officer_headers()


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ==========================================================================
# Atomic creators
# ==========================================================================
def create_season(**overrides) -> dict:
    # An explicit `name` override wins over the unique default.
    payload = F.create_season_payload(**{"name": _uniq("Season"), **overrides})
    return get_success_data(api.create_season(payload, ADMIN))


def create_division(season_id, **overrides) -> dict:
    # An explicit `name` override wins over the unique default.
    payload = F.create_division_payload(**{"name": _uniq("Div"), **overrides})
    return get_success_data(api.create_division(season_id, payload, ADMIN))


def create_player(**overrides) -> dict:
    if "email" not in overrides:
        overrides["email"] = f"{_uniq('p')}@x.com"
    payload = F.create_player_payload(**{"full_name": _uniq("Player"), **overrides})
    return get_success_data(api.create_player(payload, ADMIN))


def create_venue(**overrides) -> dict:
    payload = F.create_venue_payload(**{"name": _uniq("Venue"), **overrides})
    return get_success_data(api.create_venue(payload, ADMIN))


def create_referee(**overrides) -> dict:
    payload = F.create_referee_payload(**{"full_name": _uniq("Ref"), **overrides})
    return get_success_data(api.create_referee(payload, ADMIN))


def set_clock(to_iso8601):
    return get_success_data(api.set_clock(F.clock_payload(to_iso8601), ADMIN))


def get_season_version(season_id) -> int:
    return get_success_data(api.get_season(season_id, ADMIN))["version"]


def get_division_version(division_id) -> int:
    return get_success_data(api.get_division(division_id, ADMIN))["version"]


def open_season(season_id):
    """Advance a season DRAFT -> OPEN. Returns the OPEN season."""
    v = get_season_version(season_id)
    return get_success_data(
        api.transition_season(season_id, F.season_transition_payload("OPEN", v), ADMIN)
    )


def register_team(division_id, captain_player_id, **overrides) -> dict:
    """Register a team into a division as its captain (ownership-gated)."""
    dv = get_division_version(division_id)
    payload = F.create_team_payload(captain_player_id, dv, name=_uniq("Team"), **overrides)
    return get_success_data(
        api.create_team(division_id, payload, make_team_captain_headers(captain_player_id))
    )


def confirm_team(team_id) -> dict:
    return get_success_data(api.confirm_team(team_id, ADMIN))


def pay_fee(team_id, captain_player_id, amount_cents) -> dict:
    return get_success_data(
        api.pay_fee(team_id, F.fee_payload(amount_cents), make_team_captain_headers(captain_player_id))
    )


def schedule_game(division_id, home_team_id, away_team_id, venue_id, **overrides) -> dict:
    payload = F.create_game_payload(home_team_id, away_team_id, venue_id, **overrides)
    return get_success_data(api.create_game(division_id, payload, ADMIN))


def assign_referee(game_id, referee_id, role="HEAD") -> dict:
    return get_success_data(
        api.create_referee_assignment(game_id, {"referee_id": referee_id, "role": role}, ADMIN)
    )


# ==========================================================================
# Tier 2: Active division with two CONFIRMED teams (the most common base)
# ==========================================================================
def setup_open_division(**season_overrides):
    """Empty DB -> a season advanced to OPEN with one division and clock set to a
    point inside the registration window.

    Returns dict with keys: season, division.
    """
    season = create_season(**season_overrides)
    division = create_division(season["id"])
    set_clock("2026-08-15T00:00:00Z")
    season = open_season(season["id"])
    return {"season": season, "division": division}


def setup_division_with_two_confirmed_teams(
    division_overrides=None, season_overrides=None,
    pay_each_fee=None, fee_amount=None,
):
    """OPEN season + division + two CONFIRMED teams (each captain a distinct Player).

    If the division charges a fee (registration_fee_cents > 0) or pay_each_fee is
    truthy, each team pays `fee_amount` (defaults to the division's
    registration_fee_cents) before confirmation.

    Returns dict: season, division, home_player, away_player, home_team, away_team.
    """
    division_overrides = dict(division_overrides or {})
    season_overrides = dict(season_overrides or {})

    season = create_season(**season_overrides)
    division = create_division(season["id"], **division_overrides)
    home_player = create_player()
    away_player = create_player()
    set_clock("2026-08-15T00:00:00Z")
    open_season(season["id"])

    home_team = register_team(division["id"], home_player["id"])
    away_team = register_team(division["id"], away_player["id"])

    fee = division.get("registration_fee_cents", 0)
    needs_fee = pay_each_fee if pay_each_fee is not None else fee > 0
    if needs_fee:
        amt = fee_amount if fee_amount is not None else fee
        pay_fee(home_team["id"], home_player["id"], amt)
        pay_fee(away_team["id"], away_player["id"], amt)

    home_team = confirm_team(home_team["id"])
    away_team = confirm_team(away_team["id"])

    return {
        "season": season,
        "division": division,
        "home_player": home_player,
        "away_player": away_player,
        "home_team": home_team,
        "away_team": away_team,
    }


# ==========================================================================
# Tier 3: A scheduled game (with a venue + optional HEAD referee)
# ==========================================================================
def setup_scheduled_game(
    venue_overrides=None, game_overrides=None,
    division_overrides=None, season_overrides=None,
    with_head_referee=True,
):
    """OPEN season + division + two CONFIRMED teams + venue + one SCHEDULED game,
    optionally with a HEAD referee assigned.

    Returns dict including: season, division, venue, referee (or None), game,
    home_team, away_team, home_player, away_player, assignment (or None).
    """
    base = setup_division_with_two_confirmed_teams(
        division_overrides=division_overrides, season_overrides=season_overrides
    )
    venue = create_venue(**(venue_overrides or {}))
    referee = create_referee() if with_head_referee else None

    game = schedule_game(
        base["division"]["id"], base["home_team"]["id"], base["away_team"]["id"],
        venue["id"], **(game_overrides or {})
    )

    assignment = None
    if with_head_referee:
        assignment = assign_referee(game["id"], referee["id"], "HEAD")

    base.update({"venue": venue, "referee": referee, "game": game, "assignment": assignment})
    return base


def advance_to(season_id, target, force=False):
    """Advance a season one step to `target`, supplying the current version.

    PRD §3.1: closing early — before `clock_now` has reached `registration_closes_at`
    — is the administrator's documented prerogative via the `force` flag. These setups
    drive the clock to control refund/eligibility timing rather than the close date, so
    the OPEN->CLOSED step always supplies `force`.
    """
    v = get_season_version(season_id)
    if target == "CLOSED":
        force = True
    payload = F.season_transition_payload(target, v, **({"force": True} if force else {}))
    return get_success_data(api.transition_season(season_id, payload, ADMIN))


def advance_through_to_in_play(season_id, earliest_start="2026-09-15T18:30:00Z"):
    """From OPEN: CLOSED -> SCHEDULED -> (clock to kickoff) -> IN_PLAY.

    Requires every division already to hold >= 2 CONFIRMED teams and every REGULAR
    game SCHEDULED with venue/field/HEAD referee.
    Returns the IN_PLAY season.
    """
    advance_to(season_id, "CLOSED")
    advance_to(season_id, "SCHEDULED")
    set_clock(earliest_start)
    return advance_to(season_id, "IN_PLAY")


def setup_in_play_game_pending(venue_overrides=None, game_overrides=None,
                               division_overrides=None, season_overrides=None):
    """A SCHEDULED game (score PENDING) with a HEAD referee, in an IN_PLAY season,
    clock past kickoff so a score may be submitted.

    Returns the setup_scheduled_game dict (season now IN_PLAY).
    """
    s = setup_scheduled_game(
        venue_overrides=venue_overrides, game_overrides=game_overrides,
        division_overrides=division_overrides, season_overrides=season_overrides,
        with_head_referee=True,
    )
    advance_through_to_in_play(s["season"]["id"])
    s["season"] = get_success_data(api.get_season(s["season"]["id"], ADMIN))
    return s


def submit_and_confirm_score(game_id, referee_id, home_score, away_score):
    """Submit then confirm a score for an IN_PLAY game (referee as both actor).

    Returns the confirmed Game.
    """
    gv = get_success_data(api.get_game(game_id, ADMIN))["version"]
    ref_headers = make_referee_headers(referee_id)
    get_success_data(
        api.submit_score(game_id, F.submit_score_payload(home_score, away_score, gv), ref_headers)
    )
    return get_success_data(api.confirm_score(game_id, ref_headers))


# ==========================================================================
# Tier: Conduct report progression
# ==========================================================================
def file_and_uphold_report(game_id, player_id, severity):
    """File a conduct report, review it, and uphold it. Returns the UPHELD report."""
    report = get_success_data(
        api.create_conduct_report(F.conduct_report_payload(game_id, player_id, severity), OFFICER)
    )
    rid = report["id"]
    get_success_data(api.transition_conduct_report(rid, F.transition_payload("UNDER_REVIEW"), OFFICER))
    return get_success_data(api.transition_conduct_report(rid, F.transition_payload("UPHELD"), OFFICER))


def file_and_review_report(game_id, player_id, severity):
    """File a conduct report and move it to UNDER_REVIEW. Returns the report (UNDER_REVIEW)."""
    report = get_success_data(
        api.create_conduct_report(F.conduct_report_payload(game_id, player_id, severity), OFFICER)
    )
    rid = report["id"]
    return get_success_data(
        api.transition_conduct_report(rid, F.transition_payload("UNDER_REVIEW"), OFFICER)
    )


NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
