"""Pre-built role headers for every role in the PRD (§2.1).

`Client` and `Talent` are entity-backed roles: their X-User-ID must equal the
acting record's `id` whenever the call is ownership-gated. Use the per-instance
builders for those; the shared constants are fallbacks for non-ownership tests
only. The remaining roles are opaque operator identities.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "casting_director_headers": build_user_headers("test-casting-director-1", "CastingDirector"),
    "studio_engineer_headers": build_user_headers("test-studio-engineer-1", "StudioEngineer"),
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # Entity-backed roles — fallback for non-ownership tests only.
    "client_headers": build_user_headers("test-client-1", "Client"),
    "talent_headers": build_user_headers("test-talent-1", "Talent"),
}


def make_client_headers(client_id: str) -> dict:
    """Client is entity-backed: pass the actual Client.id as user_id whenever
    the call is ownership-gated (project creation, select_talent, cancel, ...)."""
    return build_user_headers(client_id, "Client")


def make_talent_headers(talent_id: str) -> dict:
    """Talent is entity-backed: pass the actual Talent.id as user_id whenever
    the call is ownership-gated (self-audition submission)."""
    return build_user_headers(talent_id, "Talent")
