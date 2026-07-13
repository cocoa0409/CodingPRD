"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - PlatformAdmin and CustomerService are opaque operator identities: the
#     server never compares their X-User-ID to any entity id, so a shared
#     constant is the canonical form.
#   - The Customer/Pro fallbacks are for tests that do NOT exercise ownership
#     (e.g. 4xx-on-bad-payload where the request is rejected before ownership).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "cs_headers": build_user_headers("cs-1", "CustomerService"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "pro_headers": build_user_headers("test-pro-1", "Pro"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "Customer")


def make_pro_headers(pro_id: str) -> dict:
    """For Pro (entity_backed:Pro). Pass the actual Pro.id as user_id whenever
    the call is ownership-gated."""
    return build_user_headers(pro_id, "Pro")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_cs_headers(user_id: str = "cs-1") -> dict:
    return build_user_headers(user_id, "CustomerService")
