"""Pre-built role headers for every role in the PRD.

Three roles: Client (entity_backed), Researcher (entity_backed), ProjectManager
(opaque operator). Client and Researcher headers must carry the acting entity's
real id when a call is ownership-gated or identity-stamped; use the per-instance
builders below for those.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque ProjectManager role, and for tests that
# do not exercise ownership/identity (e.g. 401/403/404 negative cases).
TEST_USERS = {
    "project_manager_headers": build_user_headers("pm-operator-1", "ProjectManager"),
    # Fallbacks for entity_backed roles — only for non-ownership negative tests.
    "client_headers": build_user_headers("test-client-1", "Client"),
    "researcher_headers": build_user_headers("test-researcher-1", "Researcher"),
}


def make_client_headers(user_id: str) -> dict:
    """For the Client role (entity_backed:Client). Pass the actual Client.id as
    user_id whenever the call is ownership-gated (deliverable accept /
    request-revision compare the project's client_id to X-User-ID)."""
    return build_user_headers(user_id, "Client")


def make_researcher_headers(user_id: str) -> dict:
    """For the Researcher role (entity_backed:Researcher). Pass the actual
    Researcher.id as user_id; the server stamps it as performed_by_id /
    researcher_id on artifacts the researcher produces."""
    return build_user_headers(user_id, "Researcher")


def make_project_manager_headers(user_id: str = "pm-operator-1") -> dict:
    """For the ProjectManager role (opaque operator, not tied to an entity)."""
    return build_user_headers(user_id, "ProjectManager")
