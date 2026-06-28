"""Pre-built role headers for every role in the PRD.

OpsAdmin is an opaque operator identity (X-User-ID not tied to any entity), so
its shared constant is the canonical form. AccountHolder and Inspector are
entity_backed roles whose X-User-ID must equal the acting Account.id /
Inspector.id for ownership checks — those tests use the per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque OpsAdmin role and for tests that do
# not exercise ownership (e.g., 401/403/404 paths, role-forbidden checks).
TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "account_holder_headers": build_user_headers("test-account-holder-1", "AccountHolder"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
}


def make_ops_admin_headers(user_id: str = "test-ops-admin-1") -> dict:
    """OpsAdmin is opaque; any user_id works for ownership purposes."""
    return build_user_headers(user_id, "OpsAdmin")


def make_account_holder_headers(user_id: str) -> dict:
    """For AccountHolder (entity_backed:Account). Pass the acting Account.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "AccountHolder")


def make_inspector_headers(user_id: str) -> dict:
    """For Inspector (entity_backed:Inspector). Pass the acting Inspector.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Inspector")
