"""Pre-built role headers for every role in the PRD (§2.1).

`BranchOps` and `Customer` are the two roles whose `X-User-ID` is the id of a
persisted entity (a branch and a customer respectively), so ownership-gated
calls MUST use the per-instance builders below with the real entity id. The
remaining three roles carry opaque operator handles.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator handles.
FLEET_ADMIN_ID = "admin-ops-1"
SECOND_FLEET_ADMIN_ID = "admin-ops-2"
LEASING_AGENT_ID = "agent-77"
ASSESSOR_ID = "inspector-9"
SECOND_ASSESSOR_ID = "inspector-12"

# Shared constants — safe for the three opaque roles, and for tests that never
# exercise ownership on an entity-backed role.
TEST_USERS = {
    "fleet_admin_headers": build_user_headers(FLEET_ADMIN_ID, "FleetAdmin"),
    "second_fleet_admin_headers": build_user_headers(
        SECOND_FLEET_ADMIN_ID, "FleetAdmin"),
    "leasing_agent_headers": build_user_headers(LEASING_AGENT_ID, "LeasingAgent"),
    "damage_assessor_headers": build_user_headers(ASSESSOR_ID, "DamageAssessor"),
    "second_damage_assessor_headers": build_user_headers(
        SECOND_ASSESSOR_ID, "DamageAssessor"),
    # entity_backed roles: fallbacks for non-ownership tests only.
    "branch_ops_headers": build_user_headers("test-branch-ops-1", "BranchOps"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_fleet_admin_headers(user_id: str = FLEET_ADMIN_ID) -> dict:
    """FleetAdmin's X-User-ID is an opaque operator handle, but it is recorded
    as `approved_by_user_id` and compared against `assessor_user_id`."""
    return build_user_headers(user_id, "FleetAdmin")


def make_leasing_agent_headers(user_id: str = LEASING_AGENT_ID) -> dict:
    return build_user_headers(user_id, "LeasingAgent")


def make_damage_assessor_headers(user_id: str = ASSESSOR_ID) -> dict:
    """DamageAssessor's X-User-ID is the handle stamped on `assessor_user_id`."""
    return build_user_headers(user_id, "DamageAssessor")


def make_branch_ops_headers(branch_id: str) -> dict:
    """For BranchOps. Pass the acting Branch's own `id`: it is matched against
    a logistics job's `origin_branch_id` and a refurbishment order's
    `branch_id`."""
    return build_user_headers(branch_id, "BranchOps")


def make_customer_headers(customer_id: str) -> dict:
    """For Customer. Pass the acting Customer's own `id`: it is matched against
    the `customer_id` of the lease behind the addressed resource."""
    return build_user_headers(customer_id, "Customer")


def make_headers(user_id: str, role: str) -> dict:
    """Escape hatch for negative auth tests (unknown roles, partial headers)."""
    return build_user_headers(user_id, role)
