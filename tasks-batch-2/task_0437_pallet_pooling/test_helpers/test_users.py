"""Pre-built role headers for every role in the PRD (§2.1).

PoolAdmin and PoolOperator are opaque identities — X-User-ID is an opaque
operator identifier never matched against an entity id. Participant is
entity_backed:Account — X-User-ID must equal the acting Account.id for
ownership checks, so a per-instance builder is provided.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - PoolAdmin / PoolOperator are opaque: the shared constant is canonical.
#   - Participant shared constant is a fallback for tests that do NOT exercise
#     account ownership (e.g. 401/403/404 paths). For ownership-gated calls use
#     make_participant_headers(account_id).
TEST_USERS = {
    "pool_admin_headers": build_user_headers("test-pool-admin-1", "PoolAdmin"),
    "pool_operator_headers": build_user_headers("test-pool-operator-1", "PoolOperator"),
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
}


def make_pool_admin_headers(user_id: str = "test-pool-admin-1") -> dict:
    """PoolAdmin (opaque identity)."""
    return build_user_headers(user_id, "PoolAdmin")


def make_pool_operator_headers(user_id: str = "test-pool-operator-1") -> dict:
    """PoolOperator (opaque identity)."""
    return build_user_headers(user_id, "PoolOperator")


def make_participant_headers(account_id: str) -> dict:
    """Participant (entity_backed:Account). Pass the acting Account.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(account_id, "Participant")
