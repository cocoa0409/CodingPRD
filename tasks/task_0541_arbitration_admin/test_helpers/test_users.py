"""Pre-built role headers for every role in the PRD.

Three roles: CaseAdministrator (opaque operator id), Party (X-User-ID is a
Party.id), and Neutral (X-User-ID is a Neutral.id). Ownership-gated calls MUST
use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque CaseAdministrator, and for tests that
# do not exercise Party/Neutral ownership (e.g. 401/403/404 negative checks).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "CaseAdministrator"),
    "party_headers": build_user_headers("test-party-1", "Party"),
    "neutral_headers": build_user_headers("test-neutral-1", "Neutral"),
    # Unknown role: exercises ERR_UNAUTHENTICATED.
    "unknown_headers": build_user_headers("test-anon-1", "Anonymous"),
}


def make_admin_headers() -> dict:
    """CaseAdministrator is opaque; the id is never compared to any entity."""
    return TEST_USERS["admin_headers"]


def make_party_headers(user_id: str) -> dict:
    """For a Party (entity_backed:Party). Pass the actual Party.id whenever the
    call is ownership-gated (ranking withdraw, appeal filing)."""
    return build_user_headers(user_id, "Party")


def make_neutral_headers(user_id: str) -> dict:
    """For a Neutral (entity_backed:Neutral). Pass the actual Neutral.id whenever
    the call is ownership-gated (candidate disclosure)."""
    return build_user_headers(user_id, "Neutral")


def make_unknown_headers(user_id: str = "test-anon-1") -> dict:
    """Headers naming a role the system does not recognize."""
    return build_user_headers(user_id, "Anonymous")
