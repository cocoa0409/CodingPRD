"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, admin-acted calls).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "CoopAdmin"),
    "gin_operator_headers": build_user_headers("gin-op-1", "GinOperator"),
    "classing_clerk_headers": build_user_headers("test-clerk-1", "ClassingClerk"),
    "warehouse_manager_headers": build_user_headers("wm-1", "WarehouseManager"),
    "accountant_headers": build_user_headers("test-accountant-1", "CoopAccountant"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "grower_headers": build_user_headers("test-grower-1", "Grower"),
}


# Per-instance builders. The opaque-role builders exist so segregation-of-duties
# scenarios can pick distinct operator identities (e.g. the user who ginned a
# module vs. the user who issues the warehouse receipt).
def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "CoopAdmin")


def make_gin_operator_headers(user_id: str) -> dict:
    """GinOperator is opaque; the id is recorded as ginned_by_user_id at
    complete-ginning and later compared for segregation of duties."""
    return build_user_headers(user_id, "GinOperator")


def make_classing_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    return build_user_headers(user_id, "ClassingClerk")


def make_warehouse_manager_headers(user_id: str) -> dict:
    """WarehouseManager is opaque; pick an id distinct from the ginning
    operator's id whenever issuing a receipt."""
    return build_user_headers(user_id, "WarehouseManager")


def make_accountant_headers(user_id: str = "test-accountant-1") -> dict:
    return build_user_headers(user_id, "CoopAccountant")


def make_grower_headers(user_id: str) -> dict:
    """For Grower (entity_backed:Grower). Pass the actual Grower.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Grower")
