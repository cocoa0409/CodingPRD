"""Pre-built role headers for every role in the PRD (section 2.1).

Identity rules (PRD 2.1):
- Agent: X-User-ID is the id of the acting AgentProfile (entity-backed).
- Guardian: X-User-ID is the id of the acting Guardian (entity-backed).
- CastingDirector / CastingAssociate / ProductionCoordinator: X-User-ID is an
  opaque operator identifier not tied to any persisted entity.

Shared constants are safe for opaque roles and for tests that never exercise
ownership. For entity-backed roles, ALWAYS use the per-instance builders with
the actual entity id whenever the call is ownership-gated (submitting as an
agent, withdrawing, confirming/declining an appointment, countering or
accepting an offer, guardian reads).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — canonical shared form.
    "director_headers": build_user_headers("test-director-1", "CastingDirector"),
    "associate_headers": build_user_headers("test-associate-1", "CastingAssociate"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "ProductionCoordinator"),
    # Entity-backed roles — fallback for non-ownership tests ONLY.
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    "guardian_headers": build_user_headers("test-guardian-1", "Guardian"),
}


def make_agent_headers(agent_profile_id: str) -> dict:
    """Agent role is entity-backed by AgentProfile: pass the AgentProfile.id."""
    return build_user_headers(agent_profile_id, "Agent")


def make_guardian_headers(guardian_id: str) -> dict:
    """Guardian role is entity-backed by Guardian: pass the Guardian.id."""
    return build_user_headers(guardian_id, "Guardian")


def make_director_headers(user_id: str = "test-director-1") -> dict:
    return build_user_headers(user_id, "CastingDirector")


def make_associate_headers(user_id: str = "test-associate-1") -> dict:
    return build_user_headers(user_id, "CastingAssociate")


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "ProductionCoordinator")
