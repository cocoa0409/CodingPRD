"""Pre-built role headers for every role in the PRD.

- Client and Coach are entity-backed: ownership checks compare X-User-ID to the
  resource's client_id / coach_id, so ownership-gated calls MUST use the
  per-instance builders with the real entity id.
- CareerAdmin is opaque: the server accepts X-User-ID for auditing but never
  compares it to any entity id, so the shared constant is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque CareerAdmin role, and for tests that do
# not exercise ownership (e.g. 401/404/validation shape checks).
TEST_USERS = {
    "client_headers": build_user_headers("test-client-1", "Client"),
    "coach_headers": build_user_headers("test-coach-1", "Coach"),
    "admin_headers": build_user_headers("test-admin-1", "CareerAdmin"),
}


def make_client_headers(user_id: str) -> dict:
    """For a Client. Pass the acting Client's id whenever the call is
    ownership-gated (order/deliverable/revision/session/claim mutations)."""
    return build_user_headers(user_id, "Client")


def make_coach_headers(user_id: str) -> dict:
    """For a Coach. Pass the acting Coach's id whenever the call is
    ownership-gated (session complete/no-show verify session.coach_id)."""
    return build_user_headers(user_id, "Coach")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For CareerAdmin (opaque identity)."""
    return build_user_headers(user_id, "CareerAdmin")
