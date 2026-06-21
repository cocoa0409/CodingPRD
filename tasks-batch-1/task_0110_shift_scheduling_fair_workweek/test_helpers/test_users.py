"""Pre-built role headers for every role in the PRD.

Manager identity is opaque (an operator id never tied to an entity), so its
shared constant is canonical. Worker identity is entity_backed:Worker — its
X-User-ID must equal the acting Worker's id for ownership checks to pass, so
ownership-gated calls MUST use make_worker_headers(worker_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque Manager id used for all manager-driven mutations and setup.
MANAGER_USER_ID = "mgr-1"

TEST_USERS = {
    # Manager: opaque role, shared constant is canonical.
    "manager_headers": build_user_headers(MANAGER_USER_ID, "Manager"),
    # Worker: shared constant is a fallback for NON-ownership tests only
    # (e.g. role-permission 403 where no resource ownership is exercised).
    "worker_headers": build_user_headers("test-worker-1", "Worker"),
}


def make_manager_headers(user_id: str = MANAGER_USER_ID) -> dict:
    """For Manager (opaque). Any operator id works; the server records but
    never compares it to an entity id."""
    return build_user_headers(user_id, "Manager")


def make_worker_headers(user_id: str) -> dict:
    """For Worker (entity_backed:Worker). Pass the actual Worker.id as user_id
    whenever the call is ownership-gated (confirm, withdraw, time-off cancel,
    swap actions, bidding)."""
    return build_user_headers(user_id, "Worker")
