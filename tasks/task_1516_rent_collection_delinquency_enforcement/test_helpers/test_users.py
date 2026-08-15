"""Pre-built role headers for every role in PRD 2.1.

Shared constants are safe for opaque roles (PropertyManager, LeasingAgent,
SystemOps) and for tests whose outcome does not depend on caller identity.
The Tenant role is entity-backed: whenever a call is ownership-gated, build
headers with make_tenant_headers(<Tenant.id>).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "property_manager_headers": build_user_headers("pm-1", "PropertyManager"),
    "property_manager_2_headers": build_user_headers("pm-2", "PropertyManager"),
    "leasing_agent_headers": build_user_headers("agent-1", "LeasingAgent"),
    # Fallback for non-ownership calls only; ownership-gated calls MUST use
    # make_tenant_headers(<actual Tenant.id>).
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
    "system_ops_headers": build_user_headers("ops-1", "SystemOps"),
}

# A header dict with no auth headers at all, for the unauthenticated probes.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_property_manager_headers(user_id: str) -> dict:
    """Opaque identity; distinct user ids drive segregation-of-duties checks."""
    return build_user_headers(user_id, "PropertyManager")


def make_leasing_agent_headers(user_id: str) -> dict:
    """Opaque identity; recorded as created_by_user_id / drafted_by_user_id."""
    return build_user_headers(user_id, "LeasingAgent")


def make_tenant_headers(user_id: str) -> dict:
    """Entity-backed identity: pass the acting Tenant record's id."""
    return build_user_headers(user_id, "Tenant")


def make_system_ops_headers(user_id: str) -> dict:
    """Opaque automation identity for the sweep and the logical clock."""
    return build_user_headers(user_id, "SystemOps")
