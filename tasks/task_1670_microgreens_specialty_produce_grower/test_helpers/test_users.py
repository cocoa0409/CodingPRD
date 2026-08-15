"""Pre-built role headers for every role in the PRD (§2.1).

Grower and OpsManager are opaque identities: X-User-ID is not tied to any
persisted entity. Chef is entity-backed by Customer: X-User-ID is the acting
Customer's id, and ownership checks compare a resource's customer_id field to
it. Ownership-gated Chef calls MUST use make_chef_headers(customer["id"]) with
the real Customer id — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "grower_headers": build_user_headers("test-grower-1", "Grower"),
    "ops_manager_headers": build_user_headers("test-ops-manager-1", "OpsManager"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only; ownership-gated calls must use make_chef_headers().
    "chef_headers": build_user_headers("test-chef-1", "Chef"),
}


def make_grower_headers(user_id: str = "test-grower-1") -> dict:
    return build_user_headers(user_id, "Grower")


def make_ops_manager_headers(user_id: str = "test-ops-manager-1") -> dict:
    return build_user_headers(user_id, "OpsManager")


def make_chef_headers(customer_id: str) -> dict:
    """For Chef (entity_backed:Customer). Pass the acting Customer.id whenever
    the call is ownership-gated (standing orders, line changes, confirms,
    cancels, spoilage reports)."""
    return build_user_headers(customer_id, "Chef")
