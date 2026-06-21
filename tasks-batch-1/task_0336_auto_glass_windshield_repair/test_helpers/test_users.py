"""Pre-built role headers for every role in the PRD.

Two roles are entity_backed (ownership enforced via X-User-ID): Customer
(X-User-ID == Customer.id) and Technician (X-User-ID == Technician.id). For
those, ownership-gated calls MUST use the per-instance builder seeded with the
actual entity id. The other two roles (ServiceAdvisor, ShopManager) are opaque
operator identities and use shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for entity_backed roles in
# tests that do NOT exercise ownership (e.g. 401/403/404/400 paths).
TEST_USERS = {
    # opaque operator identities — shared constant is the canonical form.
    "service_advisor_headers": build_user_headers("advisor-1", "ServiceAdvisor"),
    "shop_manager_headers": build_user_headers("manager-1", "ShopManager"),
    # entity_backed roles — shared constant is a fallback for non-ownership tests.
    "customer_headers": build_user_headers("customer-fallback-1", "Customer"),
    "technician_headers": build_user_headers("technician-fallback-1", "Technician"),
}


# Per-instance builders — required for every entity_backed role.
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (open work order / pay)."""
    return build_user_headers(user_id, "Customer")


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id
    as user_id whenever the server identifies the actor (check-in, start-service,
    finish-install, recalibration pass/fail/retry/create)."""
    return build_user_headers(user_id, "Technician")


def make_service_advisor_headers(user_id: str = "advisor-1") -> dict:
    """ServiceAdvisor is opaque; X-User-ID is not tied to any entity."""
    return build_user_headers(user_id, "ServiceAdvisor")


def make_shop_manager_headers(user_id: str = "manager-1") -> dict:
    """ShopManager is opaque; X-User-ID is not tied to any entity."""
    return build_user_headers(user_id, "ShopManager")
