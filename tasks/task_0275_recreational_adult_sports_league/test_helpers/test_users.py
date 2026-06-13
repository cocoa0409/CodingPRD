"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
- TeamCaptain: X-User-ID is the acting Player.id; ownership checks compare a
  resource's player-valued FK to X-User-ID. Use make_team_captain_headers(player_id).
- Referee: X-User-ID is the acting Referee.id; ownership checks compare referee_id
  to X-User-ID. Use make_referee_headers(referee_id).
- LeagueAdmin / ConductOfficer: X-User-ID is an opaque operator id, not tied to any
  entity — the shared constant is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise ownership.
TEST_USERS = {
    "league_admin_headers": build_user_headers("admin-operator-1", "LeagueAdmin"),
    "conduct_officer_headers": build_user_headers("conduct-officer-1", "ConductOfficer"),
    # Fallbacks for entity_backed roles — ONLY for non-ownership tests (e.g. 401/403/404).
    "team_captain_headers": build_user_headers("captain-fallback-1", "TeamCaptain"),
    "referee_headers": build_user_headers("referee-fallback-1", "Referee"),
}


def make_league_admin_headers(user_id: str = "admin-operator-1") -> dict:
    """LeagueAdmin (opaque). X-User-ID is not ownership-scoped."""
    return build_user_headers(user_id, "LeagueAdmin")


def make_conduct_officer_headers(user_id: str = "conduct-officer-1") -> dict:
    """ConductOfficer (opaque). X-User-ID is not ownership-scoped."""
    return build_user_headers(user_id, "ConductOfficer")


def make_team_captain_headers(player_id: str) -> dict:
    """TeamCaptain (entity_backed:Player). Pass the acting Player.id whenever the
    call is ownership-gated (registration, roster, reschedule, dispute, appeal)."""
    return build_user_headers(player_id, "TeamCaptain")


def make_referee_headers(referee_id: str) -> dict:
    """Referee (entity_backed:Referee). Pass the acting Referee.id whenever the
    call is ownership-gated (score confirmation by the HEAD-assigned referee)."""
    return build_user_headers(referee_id, "Referee")
