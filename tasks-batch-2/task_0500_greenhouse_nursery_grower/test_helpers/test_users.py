"""Pre-built role headers for every role in the PRD.

Three roles (GrowerManager, ProductionTech, SalesCoordinator) are opaque operator
identities — the shared constants are the canonical form for them. The Broker role
is entity-backed (X-User-ID must equal the acting Broker.id), so ownership-gated
calls MUST use make_broker_headers(broker_id) with the real broker id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "grower_manager_headers": build_user_headers("test-grower-1", "GrowerManager"),
    "production_tech_headers": build_user_headers("test-tech-1", "ProductionTech"),
    "sales_coordinator_headers": build_user_headers("test-sales-1", "SalesCoordinator"),
    # entity_backed Broker: shared constant is a fallback for non-ownership tests only.
    "broker_headers": build_user_headers("test-broker-1", "Broker"),
}


def make_broker_headers(broker_id: str) -> dict:
    """For the entity-backed Broker role. Pass the actual Broker.id whenever the
    call is ownership-gated (creating/editing the broker's own orders/lines)."""
    return build_user_headers(broker_id, "Broker")


def make_role_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary (possibly unknown) role — used for auth tests."""
    return build_user_headers(user_id, role)
