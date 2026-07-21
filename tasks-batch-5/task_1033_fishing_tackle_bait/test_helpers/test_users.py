"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed (Customer, Guide): their X-User-ID must equal the
actual entity id whenever a call is ownership-gated, so a per-instance builder
is provided. The three opaque roles (ShopClerk, TournamentDirector, ShopManager)
use shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#   - opaque roles: this is the canonical form.
#   - entity_backed roles (customer/guide): fallback for tests that do NOT
#     exercise ownership (e.g. 400/404/403 checks). Ownership-gated calls MUST
#     use the make_*_headers builders below with the real entity id.
TEST_USERS = {
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "clerk_headers": build_user_headers("test-clerk-1", "ShopClerk"),
    "guide_headers": build_user_headers("test-guide-1", "Guide"),
    "director_headers": build_user_headers("test-director-1", "TournamentDirector"),
    "manager_headers": build_user_headers("test-manager-1", "ShopManager"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the real Customer.id as
    user_id whenever the call is ownership-gated (own booking/entry/order)."""
    return build_user_headers(user_id, "Customer")


def make_guide_headers(user_id: str) -> dict:
    """For Guide (entity_backed:Guide). Pass the real Guide.id as user_id
    whenever the call is ownership-gated (completing own booking, PATCH own)."""
    return build_user_headers(user_id, "Guide")
