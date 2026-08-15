"""Pre-built role headers for every role in the PRD (§2.1, §4).

Identity semantics (PRD §2.1): ShopManager / Technician / Inspector carry
opaque identifiers; Customer carries the acting Customer entity's `id`, and
ownership-gated calls compare it against the work order's aircraft owner.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (schema failures, missing resources, RBAC denials by role).
TEST_USERS = {
    "shop_manager_headers": build_user_headers("mgr-1", "ShopManager"),
    # Opaque roles: shared constants are canonical; per-instance builders below
    # exist for calls whose recorded user id matters (performed_by / verified_by).
    "technician_headers": build_user_headers("tech-1", "Technician"),
    "inspector_headers": build_user_headers("insp-1", "Inspector"),
    # entity_backed role: shared constant is a fallback for non-ownership tests
    # only — never pass it to decide / acknowledge-overage.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


# Per-instance builders.
def make_shop_manager_headers(user_id: str = "mgr-1") -> dict:
    return build_user_headers(user_id, "ShopManager")


def make_technician_headers(user_id: str) -> dict:
    """For Technician (opaque). The id lands in performed_by_user_id on complete."""
    return build_user_headers(user_id, "Technician")


def make_inspector_headers(user_id: str) -> dict:
    """For Inspector (opaque). The id lands in verified_by_user_id / decided_by_user_id."""
    return build_user_headers(user_id, "Inspector")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id
    whenever the call is ownership-gated (decide, acknowledge-overage)."""
    return build_user_headers(user_id, "Customer")
