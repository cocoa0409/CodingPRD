"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque Scheduler role, and for tests that do
# not exercise entity ownership (e.g. 401/403/404 checks).
TEST_USERS = {
    # Scheduler is opaque: X-User-ID is an arbitrary operator id never compared
    # to any entity id, so a shared constant is the canonical form.
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    # The following entity-backed shared constants are fallbacks usable ONLY in
    # tests where success does not depend on owning the subject resource.
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "client_headers": build_user_headers("test-client-1", "Client"),
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
}


# Per-instance builders — required for every entity_backed role. Pass the actual
# entity id whenever the downstream call is ownership-gated.
def make_scheduler_headers(user_id: str = "test-scheduler-1") -> dict:
    """For the opaque Scheduler role."""
    return build_user_headers(user_id, "Scheduler")


def make_inspector_headers(user_id: str) -> dict:
    """For Inspector (entity_backed:Inspector). Pass the acting Inspector.id so
    that assigned-inspector ownership checks (start/report/submit/revise) pass."""
    return build_user_headers(user_id, "Inspector")


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the acting Client.id."""
    return build_user_headers(user_id, "Client")


def make_agent_headers(user_id: str) -> dict:
    """For Agent (entity_backed:Agent). Pass the acting Agent.id."""
    return build_user_headers(user_id, "Agent")
