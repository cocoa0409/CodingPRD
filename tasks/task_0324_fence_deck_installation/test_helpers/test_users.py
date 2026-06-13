"""Pre-built role headers for every role in the PRD (§2.1).

Four roles (ProjectManager, Estimator, FieldTech, PermitClerk) carry opaque
identities — the shared constant is the canonical form for them. The Customer
role is entity-backed: ownership checks compare the project's customer_id to
X-User-ID, so Customer headers MUST be built per-instance with the real
Customer.id via make_customer_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the four opaque operator roles, and for tests
# that do not exercise Customer ownership.
TEST_USERS = {
    "project_manager_headers": build_user_headers("test-pm-1", "ProjectManager"),
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    "field_tech_headers": build_user_headers("test-fieldtech-1", "FieldTech"),
    "permit_clerk_headers": build_user_headers("test-permitclerk-1", "PermitClerk"),
    # Fallback for Customer non-ownership tests only (e.g. forbidden checks).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual
    Customer.id as user_id whenever the call is ownership-gated (estimate
    accept, warranty claim)."""
    return build_user_headers(user_id, "Customer")


def anonymous_headers() -> dict:
    """Headers with no X-User-Role — drives ERR_UNAUTHENTICATED."""
    return {"Content-Type": "application/json"}
