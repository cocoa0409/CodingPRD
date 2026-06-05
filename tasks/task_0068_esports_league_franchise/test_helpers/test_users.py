"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # LeagueCommissioner: opaque identity — X-User-ID is not tied to any entity.
    "commissioner_headers": build_user_headers("commissioner-1", "LeagueCommissioner"),
    # TeamGM: entity_backed:Team — this shared constant is a fallback for non-ownership
    # tests (e.g. 401/403/404 paths). Ownership-gated calls MUST use make_team_gm_headers().
    "team_gm_headers": build_user_headers("team-gm-1", "TeamGM"),
}


def make_commissioner_headers() -> dict:
    """LeagueCommissioner headers (opaque identity)."""
    return build_user_headers("commissioner-1", "LeagueCommissioner")


def make_team_gm_headers(team_id: str) -> dict:
    """For TeamGM (entity_backed:Team). Pass the actual Team.id as X-User-ID
    whenever the call is ownership-gated (sign/promote/waive/trade on own team)."""
    return build_user_headers(team_id, "TeamGM")
