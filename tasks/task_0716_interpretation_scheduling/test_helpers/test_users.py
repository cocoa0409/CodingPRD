"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin, CoordinatorOps), and for
# tests that do not exercise ownership. ClientAccount/Interpreter are entity_backed:
# the shared constant here is a fallback ONLY for non-ownership tests (e.g. 400/404/403
# checks that fire before the ownership comparison).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "coordinator_headers": build_user_headers("test-coord-1", "CoordinatorOps"),
    # entity_backed fallbacks (non-ownership tests only):
    "client_headers": build_user_headers("test-client-1", "ClientAccount"),
    "interpreter_headers": build_user_headers("test-interpreter-1", "Interpreter"),
}


# Per-instance builders — required for every entity_backed role. Pass the actual
# entity id whenever the downstream call is ownership-gated.
def make_client_headers(user_id: str) -> dict:
    """For ClientAccount (entity_backed:ClientAccount). Pass the ClientAccount.id."""
    return build_user_headers(user_id, "ClientAccount")


def make_interpreter_headers(user_id: str) -> dict:
    """For Interpreter (entity_backed:Interpreter). Pass the Interpreter.id."""
    return build_user_headers(user_id, "Interpreter")


def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]


def coordinator_headers() -> dict:
    return TEST_USERS["coordinator_headers"]
