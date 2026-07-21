"""Pre-built role headers for every role in the PRD (§2.1).

The `Customer` role is entity-backed: its `X-User-ID` must equal the acting
Customer's `id` for ownership-gated operations (place/cancel/return/claim).
Use `make_customer_headers(customer_id)` in those cases. The other three roles
(`Merchandiser`, `FulfillmentOps`, `PlatformAdmin`) are opaque operators whose
identifier is never compared to any entity, so shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - Opaque roles: canonical form.
#   - Customer: a fallback ONLY for reads / tests that don't exercise ownership.
TEST_USERS = {
    "customer_headers": build_user_headers("test-customer-generic", "Customer"),
    "merchandiser_headers": build_user_headers("test-merchandiser-1", "Merchandiser"),
    "fulfillment_headers": build_user_headers("test-fulfillment-1", "FulfillmentOps"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_customer_headers(customer_id: str) -> dict:
    """Headers for the Customer role (entity_backed:Customer). Pass the actual
    Customer.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "Customer")


def make_role_headers(user_id: str, role: str) -> dict:
    """Escape hatch: build headers for an arbitrary role string (used by the
    unauthenticated-with-unknown-role test)."""
    return build_user_headers(user_id, role)
