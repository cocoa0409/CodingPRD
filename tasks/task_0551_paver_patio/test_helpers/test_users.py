"""Pre-built role headers for every role in the PRD (§2.1).

Three roles (PlatformAdmin, DesignConsultant, ProjectManager) are `opaque`:
X-User-ID is an operator id not tied to any entity, so a shared constant is
canonical. The `Client` role is entity_backed:Customer — its X-User-ID must be
the acting Customer's id, so ownership-gated calls MUST use make_client_headers().
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-op-1", "PlatformAdmin"),
    "design_consultant_headers": build_user_headers("design-op-1", "DesignConsultant"),
    "project_manager_headers": build_user_headers("pm-op-1", "ProjectManager"),
    # Shared fallback for Client — only safe for tests that do not exercise ownership.
    "client_headers": build_user_headers("client-op-1", "Client"),
}


def make_client_headers(customer_id: str) -> dict:
    """Headers for the Client role (entity_backed:Customer).

    Pass the acting Customer's id as user_id whenever the call is ownership-gated
    (design approve/request-revision, sign-contract, file warranty claim).
    """
    return build_user_headers(customer_id, "Client")
