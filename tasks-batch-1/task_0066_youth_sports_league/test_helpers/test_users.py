"""Pre-built role headers for every role in the PRD (§2.1).

Roles:
  - LeagueAdmin  : opaque operator id, not tied to any entity.
  - Coach        : opaque coach id, matched against Team.coach_user_id.
  - Referee      : entity_backed by Referee; X-User-ID == Referee.user_id.
  - ParentGuardian: entity_backed by Family; X-User-ID == Family.id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (e.g. LeagueAdmin operations, 404/400 checks).
TEST_USERS = {
    "league_admin_headers": build_user_headers("admin-1", "LeagueAdmin"),
    # Coach is opaque but ownership-gated for draft-picks; use make_coach_headers
    # with the team's coach_user_id where ownership matters.
    "coach_headers": build_user_headers("cx", "Coach"),
    # Referee/ParentGuardian shared constants are fallbacks for non-ownership
    # tests only; ownership-gated calls must use the per-instance builders below.
    "referee_headers": build_user_headers("ref-1", "Referee"),
    "parent_guardian_headers": build_user_headers("parent-1", "ParentGuardian"),
}


def make_league_admin_headers(user_id: str = "admin-1") -> dict:
    """LeagueAdmin (opaque). user_id is not tied to any entity."""
    return build_user_headers(user_id, "LeagueAdmin")


def make_coach_headers(coach_user_id: str) -> dict:
    """Coach (opaque, ownership via Team.coach_user_id). Pass the team's
    coach_user_id when the draft-pick call is ownership-gated."""
    return build_user_headers(coach_user_id, "Coach")


def make_referee_headers(user_id: str) -> dict:
    """Referee (entity_backed:Referee). Pass the acting Referee's user_id —
    NOT the Referee.id — whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Referee")


def make_parent_guardian_headers(family_id: str) -> dict:
    """ParentGuardian (entity_backed:Family). Pass the acting Family's id
    whenever the call is ownership-gated."""
    return build_user_headers(family_id, "ParentGuardian")
