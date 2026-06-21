"""Pre-built role headers for every role in the PRD (§2.1).

LeagueAdmin, Assignor and Evaluator carry opaque identities — a shared constant
is the canonical form. Official is entity-backed: ownership checks compare
X-User-ID to the assignment's official_id, so ownership-gated calls MUST use
make_official_headers(official_id) with the real Official.id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# Official ownership (e.g. 400/403/404 paths, reads).
TEST_USERS = {
    "league_admin_headers": build_user_headers("test-league-admin-1", "LeagueAdmin"),
    "assignor_headers": build_user_headers("test-assignor-1", "Assignor"),
    "evaluator_headers": build_user_headers("test-evaluator-1", "Evaluator"),
    # Fallback Official header for non-ownership tests only.
    "official_headers": build_user_headers("test-official-1", "Official"),
}


def make_official_headers(official_id: str) -> dict:
    """For the Official role (entity_backed:Official). Pass the actual Official.id
    as X-User-ID whenever the call is ownership-gated (accept/decline/withdraw/
    appeal, and declaring that official's own availability)."""
    return build_user_headers(official_id, "Official")


def make_league_admin_headers(user_id: str = "test-league-admin-1") -> dict:
    return build_user_headers(user_id, "LeagueAdmin")


def make_assignor_headers(user_id: str = "test-assignor-1") -> dict:
    return build_user_headers(user_id, "Assignor")


def make_evaluator_headers(user_id: str = "test-evaluator-1") -> dict:
    return build_user_headers(user_id, "Evaluator")
