"""Pre-built role headers for every role in the Community Solar PRD (§2.1).

GridOperator and ProgramAdmin carry an opaque X-User-ID (not tied to any entity).
Subscriber's X-User-ID is the acting Subscriber's id; ownership checks compare a
resource's subscriber foreign key to X-User-ID, so ownership-gated subscriber calls
MUST use make_subscriber_headers(subscriber_id) with the real subscriber id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (GridOperator/ProgramAdmin) and for
# Subscriber tests that do NOT exercise ownership (401/403/404/400-on-bad-payload).
TEST_USERS = {
    "grid_operator_headers": build_user_headers("test-grid-operator-1", "GridOperator"),
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    # Fallback only — for ownership-gated subscriber calls, use make_subscriber_headers().
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
}


def make_grid_operator_headers(user_id: str = "test-grid-operator-1") -> dict:
    """GridOperator headers (opaque identity)."""
    return build_user_headers(user_id, "GridOperator")


def make_program_admin_headers(user_id: str = "test-program-admin-1") -> dict:
    """ProgramAdmin headers (opaque identity)."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_subscriber_headers(user_id: str) -> dict:
    """Subscriber headers. Pass the acting Subscriber.id as user_id whenever the
    call is ownership-gated (submit/transfer/cancel/withdraw/dispute on own resource)."""
    return build_user_headers(user_id, "Subscriber")
