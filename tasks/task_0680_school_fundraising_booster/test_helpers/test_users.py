"""Pre-built role headers for every role in the PRD (§2.1).

CampaignAdmin, Treasurer, and SchoolOfficial carry an opaque X-User-ID not tied
to any entity, so a shared constant is the canonical form for those roles.

Seller is entity-backed: X-User-ID must equal the acting Seller's id. Use the
per-instance builder make_seller_headers(seller_id) whenever a Seller call is
ownership-gated (order/pledge create, read own order/pledge). The shared
constant is only a fallback for Seller tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "campaign_admin_headers": build_user_headers("test-admin-1", "CampaignAdmin"),
    "treasurer_headers": build_user_headers("test-treasurer-1", "Treasurer"),
    "school_official_headers": build_user_headers("test-official-1", "SchoolOfficial"),
    # Fallback for non-ownership Seller tests only.
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
}


def make_seller_headers(seller_id: str) -> dict:
    """For the Seller role (entity_backed:Seller). Pass the actual Seller.id as
    X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(seller_id, "Seller")
