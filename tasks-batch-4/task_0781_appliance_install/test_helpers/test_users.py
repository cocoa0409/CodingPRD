"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque PlatformAdmin role, and for tests that do
# NOT exercise per-resource ownership (401/403-by-role, 404-on-missing-resource).
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("admin-op-1", "PlatformAdmin"),
    # entity_backed roles: shared constants are fallbacks for NON-ownership tests only.
    "retailer_headers": build_user_headers("test-retailer-1", "Retailer"),
    "pro_headers": build_user_headers("test-pro-1", "Pro"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


# Per-instance builders — required for every entity_backed role. Pass the real
# entity id whenever the downstream call is ownership-gated.
def make_admin_headers(user_id: str = "admin-op-1") -> dict:
    """For PlatformAdmin (opaque identity)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_retailer_headers(user_id: str) -> dict:
    """For Retailer (entity_backed:Retailer). Pass the Retailer.id as user_id
    whenever the call is ownership-gated (create/schedule/cancel work orders)."""
    return build_user_headers(user_id, "Retailer")


def make_pro_headers(user_id: str) -> dict:
    """For Pro (entity_backed:Pro). Pass the Pro.id as user_id whenever the call is
    ownership-gated (accept/decline assignments; start/complete/parts on work orders)."""
    return build_user_headers(user_id, "Pro")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the Customer.id as user_id whenever
    the call is ownership-gated (request-redo; ratings)."""
    return build_user_headers(user_id, "Customer")
