"""Pre-built role headers for every role in the PRD.

Two of the five roles are entity-backed (Customer, Guide): their X-User-ID is the
id of a persisted record and drives ownership checks. For ownership-gated calls,
build the header with the actual entity id via the make_* builders below.
The other three roles (Anonymous, ShopClerk, ShopManager) are opaque.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (missing-resource, bad-payload, or opaque-role calls).
TEST_USERS = {
    "anonymous_headers": build_user_headers("public-visitor-1", "Anonymous"),
    # entity_backed: fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "clerk_headers": build_user_headers("test-clerk-1", "ShopClerk"),
    # entity_backed: fallback for non-ownership tests only.
    "guide_headers": build_user_headers("test-guide-1", "Guide"),
    "manager_headers": build_user_headers("test-manager-1", "ShopManager"),
}


# Per-instance builders — required for every entity_backed role whenever the call
# is ownership-gated. Pass the actual Customer.id / Guide.id.
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the acting Customer.id."""
    return build_user_headers(user_id, "Customer")


def make_guide_headers(user_id: str) -> dict:
    """For Guide (entity_backed:Guide). Pass the acting Guide.id."""
    return build_user_headers(user_id, "Guide")
