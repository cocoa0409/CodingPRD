"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- LeagueAdmin is OPAQUE. 'When X-User-Role is LeagueAdmin, X-User-ID is
  an opaque operator identifier not tied to any persisted entity.'
  Shared constants are canonical for this role.

- TeamManager is OPAQUE, but ownership is established at creation:
  'Ownership of a TeamRegistration is established at creation time by
  the rule that X-User-ID must equal the manager_id supplied in the
  request body; subsequent team-side actions on that registration ...
  require the caller's X-User-ID to match the same manager_id.'
  → For team-side actions on a specific registration, fixtures MUST use
  make_team_manager_headers(manager_id) with the manager_id that was
  bound to the registration. The shared 'team_manager_headers' constant
  is the canonical manager_id used at creation time (TEAM_MANAGER_ID).

- Player is ENTITY-BACKED (Player.X-User-ID == PlayerContract.player_id):
  'Ownership checks on contract-signing endpoints compare
  PlayerContract.player_id to X-User-ID.'
  → A test signing as a Player MUST use make_player_headers(player_id),
  not a shared constant — every shared constant would fail the ownership
  check on the player-sign endpoint.

- Referee is ENTITY-BACKED (Referee.X-User-ID == Referee.user_id):
  'When X-User-Role is Referee, X-User-ID is the id ... of the acting
  Referee; ownership checks on any resource that references a Referee
  compare the resource's referee foreign-key field ... to X-User-ID.'
  → A test acting as a Referee MUST use make_referee_headers(user_id)
  with the registered Referee's user_id.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Canonical opaque-role manager_id used by fixtures that need a stable
# default for ownership checks via make_team_manager_headers().
TEAM_MANAGER_ID = "tm-default-001"
TEAM_MANAGER_ID_ALT = "tm-default-002"

LEAGUE_ADMIN_ID = "admin-001"
LEAGUE_ADMIN_ID_ALT = "admin-002"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # LeagueAdmin (opaque) — canonical shared constants.
    "league_admin_headers": build_user_headers(LEAGUE_ADMIN_ID, "LeagueAdmin"),
    "league_admin_headers_alt": build_user_headers(
        LEAGUE_ADMIN_ID_ALT, "LeagueAdmin",
    ),

    # TeamManager (opaque but ownership-binding). The shared constant is
    # the canonical manager_id used when a fixture creates a single
    # registration without an explicit override. For multi-team tests,
    # fixtures pass explicit manager_id values per team and build
    # headers via make_team_manager_headers().
    "team_manager_headers": build_user_headers(TEAM_MANAGER_ID, "TeamManager"),
    "team_manager_headers_alt": build_user_headers(
        TEAM_MANAGER_ID_ALT, "TeamManager",
    ),

    # Player fallback — X-User-ID 'player-fallback' matches no real
    # PlayerContract.player_id. Use ONLY for tests that do not exercise
    # ownership (missing-auth, wrong-role, missing-resource).
    "player_headers": build_user_headers("player-fallback", "Player"),

    # Referee fallback — X-User-ID 'referee-fallback' matches no real
    # Referee.user_id. Use ONLY for tests that do not exercise ownership.
    "referee_headers": build_user_headers("referee-fallback", "Referee"),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity_backed roles and for the
# TeamManager ownership binding (PRD §2.1).
# ---------------------------------------------------------------------------
def make_league_admin_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: LeagueAdmin X-User-ID is opaque. Useful when a test
    wants distinct actor_user_id values on AuditLogEntry rows."""
    return build_user_headers(user_id, "LeagueAdmin")


def make_team_manager_headers(manager_id: str) -> Dict[str, str]:
    """PRD §2.1: 'Ownership of a TeamRegistration is established at
    creation time by the rule that X-User-ID must equal the manager_id
    supplied in the request body; subsequent team-side actions on that
    registration ... require the caller's X-User-ID to match the same
    manager_id.' Pass the manager_id bound at registration creation
    whenever the call is team-ownership-gated."""
    return build_user_headers(manager_id, "TeamManager")


def make_player_headers(player_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Player, X-User-ID is the id of
    the acting PlayerContract party — specifically, it must equal the
    player_id field on the PlayerContract they are attempting to sign.'
    Pass the actual PlayerContract.player_id whenever the call is
    player-ownership-gated (sign endpoint)."""
    return build_user_headers(player_id, "Player")


def make_referee_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Referee, X-User-ID is the id
    (specifically, the user_id) of the acting Referee.' Pass the
    Referee.user_id whenever the call is referee-ownership-gated."""
    return build_user_headers(user_id, "Referee")


__all__ = [
    "TEAM_MANAGER_ID",
    "TEAM_MANAGER_ID_ALT",
    "LEAGUE_ADMIN_ID",
    "LEAGUE_ADMIN_ID_ALT",
    "TEST_USERS",
    "make_league_admin_headers",
    "make_team_manager_headers",
    "make_player_headers",
    "make_referee_headers",
]
