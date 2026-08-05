"""Pre-built role headers for every role in the PRD.

Four roles are entity-backed (BrokerAgent, BrokerManager, Supplier, Customer):
their X-User-ID must be the id of a real persisted entity, so ownership-gated
calls MUST use the make_*_headers(entity_id) builders. OpsAdmin is opaque and
uses a shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque OpsAdmin role, and for negative tests
# (401/404/422) whose success does not depend on owning the subject resource.
TEST_USERS = {
    "ops_admin_headers": build_user_headers("ops-admin-1", "OpsAdmin"),
    # entity-backed fallbacks (NOT for ownership-gated calls):
    "broker_agent_headers": build_user_headers("test-agent-1", "BrokerAgent"),
    "broker_manager_headers": build_user_headers("test-manager-1", "BrokerManager"),
    "supplier_headers": build_user_headers("test-supplier-1", "Supplier"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_agent_headers(broker_user_id: str) -> dict:
    """For BrokerAgent (entity_backed:BrokerUser). Pass the AGENT BrokerUser.id."""
    return build_user_headers(broker_user_id, "BrokerAgent")


def make_manager_headers(broker_user_id: str) -> dict:
    """For BrokerManager (entity_backed:BrokerUser). Pass the MANAGER BrokerUser.id."""
    return build_user_headers(broker_user_id, "BrokerManager")


def make_supplier_headers(supplier_id: str) -> dict:
    """For Supplier (entity_backed:Supplier). Pass the Supplier.id."""
    return build_user_headers(supplier_id, "Supplier")


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the Customer.id."""
    return build_user_headers(customer_id, "Customer")


def ops_headers() -> dict:
    """OpsAdmin is opaque — a constant back-office credential."""
    return TEST_USERS["ops_admin_headers"]
