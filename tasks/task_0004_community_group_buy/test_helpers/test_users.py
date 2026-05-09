"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # Opaque roles — shared constants are canonical
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "pickup_operator_headers": build_user_headers("test-pickup-op-1", "PickupOperator"),
    "customer_service_headers": build_user_headers("test-cs-agent-1", "CustomerService"),
    # Entity-backed roles — shared constant is FALLBACK only (use builders for ownership-gated calls)
    "group_leader_headers": build_user_headers("test-leader-1", "GroupLeader"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "supplier_headers": build_user_headers("test-supplier-1", "Supplier"),
}


# Per-instance builders — required for every entity_backed role.
def make_group_leader_headers(leader_id: str) -> dict:
    """Headers for an acting GroupLeader. Pass the actual GroupLeader.id."""
    return build_user_headers(leader_id, "GroupLeader")


def make_customer_headers(customer_id: str) -> dict:
    """Headers for an acting Customer. Pass the actual Customer.id."""
    return build_user_headers(customer_id, "Customer")


def make_supplier_headers(supplier_id: str) -> dict:
    """Headers for an acting Supplier. Pass the actual Supplier.id."""
    return build_user_headers(supplier_id, "Supplier")


def make_platform_admin_headers(admin_id: str = "test-admin-1") -> dict:
    return build_user_headers(admin_id, "PlatformAdmin")


def make_pickup_operator_headers(op_id: str = "test-pickup-op-1") -> dict:
    return build_user_headers(op_id, "PickupOperator")


def make_customer_service_headers(agent_id: str = "test-cs-agent-1") -> dict:
    return build_user_headers(agent_id, "CustomerService")
