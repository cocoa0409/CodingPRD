"""Pre-built role headers for every role in the PRD (§2.1).

Two of the three roles are entity-backed: a CastingDirector's X-User-ID is the id
of the acting CastingDirector entity, and a Talent's X-User-ID is the id of the
acting Talent entity. Ownership-gated calls MUST use the per-instance builders
below with the real entity id. The Agent role is opaque — its X-User-ID is not
tied to any persisted entity — so the shared constant is the canonical form for it.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque Agent role, and for tests that do not
# exercise an ownership check (e.g. 400/404/auth-shape cases).
TEST_USERS = {
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    # For entity_backed roles the shared constant is a NON-ownership fallback only.
    "casting_director_headers": build_user_headers("test-cd-1", "CastingDirector"),
    "talent_headers": build_user_headers("test-talent-1", "Talent"),
}


def make_agent_headers(user_id: str = "test-agent-1") -> dict:
    """Agent is opaque; X-User-ID is not compared to any entity id (PRD §2.1)."""
    return build_user_headers(user_id, "Agent")


def make_casting_director_headers(user_id: str) -> dict:
    """For CastingDirector (entity_backed:CastingDirector). Pass the real
    CastingDirector.id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "CastingDirector")


def make_talent_headers(user_id: str) -> dict:
    """For Talent (entity_backed:Talent). Pass the real Talent.id whenever the
    call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Talent")
