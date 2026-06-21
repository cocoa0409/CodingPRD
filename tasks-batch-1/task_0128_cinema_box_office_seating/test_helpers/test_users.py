"""Pre-built role headers for every role in the PRD.

CinemaManager, BoxOfficeAgent, and Anonymous carry opaque identities — the
shared constants below are the canonical form for them. Member and Distributor
are entity-backed: their X-User-ID must equal a real persisted entity id for
ownership checks to pass, so consumers MUST use the per-instance builders
make_member_headers(member_id) / make_distributor_headers(distributor_id)
whenever a call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership (e.g. 401/403/404 on bad payload or missing resource).
TEST_USERS = {
    "manager_headers": build_user_headers("test-manager-1", "CinemaManager"),
    "agent_headers": build_user_headers("test-agent-1", "BoxOfficeAgent"),
    # Fallbacks for entity_backed roles — use ONLY for non-ownership tests.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "distributor_headers": build_user_headers("test-distributor-1", "Distributor"),
}

# Anonymous: no X-User-ID and no X-User-Role. Used for member self-registration
# and for the unauthenticated-rejection test.
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_distributor_headers(user_id: str) -> dict:
    """For the Distributor role (entity_backed:Distributor). Pass the actual
    Distributor.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Distributor")
