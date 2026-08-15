"""Pre-built role headers for every role in PRD §2.1.

Customer is entity-backed: its X-User-ID must be the acting Customer resource's
id whenever the call is ownership-gated (spec approval, release create/cancel,
customer-scoped reads). Use make_customer_headers(customer["id"]) for those
calls; the shared constant is only a fallback for non-ownership probes.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "sales_engineer_headers": build_user_headers("sales-1", "SalesEngineer"),
    "design_engineer_headers": build_user_headers("design-1", "DesignEngineer"),
    "quality_engineer_headers": build_user_headers("quality-1", "QualityEngineer"),
    "plant_manager_headers": build_user_headers("plant-1", "PlantManager"),
    # entity_backed:Customer — fallback for non-ownership tests only.
    "customer_headers": build_user_headers("customer-orphan-1", "Customer"),
}

# A request without X-User-ID / X-User-Role headers (PRD §2.5 step 1).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}

# A request whose role value is outside the six recognized roles.
UNRECOGNIZED_ROLE_HEADERS = {
    "X-User-ID": "mystery-1",
    "X-User-Role": "Wizard",
    "Content-Type": "application/json",
}


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed by Customer: pass the acting customer's id
    whenever the call is ownership-gated (approve / release create / cancel)."""
    return build_user_headers(customer_id, "Customer")
