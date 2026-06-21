"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed: Customer (X-User-ID == Customer.id) and Technician
(X-User-ID == Technician.id). Ownership-gated calls for those roles MUST use the
per-instance builders below, threading the real entity id. The remaining roles
(ServiceAdvisor, PartsManager, ShopManager) are opaque operator identifiers
(PRD §2.1) for which the shared constant is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "service_advisor_headers": build_user_headers("test-advisor-1", "ServiceAdvisor"),
    "parts_manager_headers": build_user_headers("test-parts-1", "PartsManager"),
    "shop_manager_headers": build_user_headers("test-shop-1", "ShopManager"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests
    # only (e.g. 403-on-role, 404-on-missing). Ownership tests use the builders.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (authorize / decision)."""
    return build_user_headers(user_id, "Customer")


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id
    as user_id for clock-in / clock-out / complete calls."""
    return build_user_headers(user_id, "Technician")
