"""Pre-built request headers for each of the PRD's five roles.

PlatformAdmin, MarketplaceOps and TrustSafety carry opaque operator identifiers
that the PRD records verbatim into manifest_reviewed_by_user_id,
decided_by_user_id and reversed_by_user_id, so shared constants are the
canonical form for them.

SellerOps and Buyer are different: the PRD requires X-User-ID to equal the
SellerAccount.id / BuyerAccount.id behind the resource, so those headers MUST be
built per instance with make_seller_ops_headers() / make_buyer_headers().
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers reused across the suite.
ADMIN_USER_ID = "admin-1"
REVIEWER_USER_ID = "ops-review-1"
SECOND_REVIEWER_USER_ID = "ops-review-2"
CLAIM_DECIDER_USER_ID = "ops-claims-9"
DOCK_OPS_USER_ID = "ops-dock-1"
CLOSER_USER_ID = "ops-close-1"
SWEEPER_USER_ID = "ops-sweep-1"
TRUST_SAFETY_USER_ID = "ts-1"
SECOND_TRUST_SAFETY_USER_ID = "ts-2"

TEST_USERS = {
    # Opaque roles - the shared constant is the canonical identity.
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "marketplace_ops_headers": build_user_headers(REVIEWER_USER_ID, "MarketplaceOps"),
    "marketplace_ops_reviewer_headers": build_user_headers(REVIEWER_USER_ID, "MarketplaceOps"),
    "marketplace_ops_second_reviewer_headers": build_user_headers(
        SECOND_REVIEWER_USER_ID, "MarketplaceOps"
    ),
    "marketplace_ops_claims_headers": build_user_headers(
        CLAIM_DECIDER_USER_ID, "MarketplaceOps"
    ),
    "marketplace_ops_dock_headers": build_user_headers(DOCK_OPS_USER_ID, "MarketplaceOps"),
    "marketplace_ops_closer_headers": build_user_headers(CLOSER_USER_ID, "MarketplaceOps"),
    "marketplace_ops_sweeper_headers": build_user_headers(SWEEPER_USER_ID, "MarketplaceOps"),
    "trust_safety_headers": build_user_headers(TRUST_SAFETY_USER_ID, "TrustSafety"),
    "trust_safety_reverser_headers": build_user_headers(
        SECOND_TRUST_SAFETY_USER_ID, "TrustSafety"
    ),
    # Entity-backed roles - fallbacks for calls that never reach an ownership
    # check (for example a 403 role probe or a 404 on an unknown path id).
    "seller_ops_headers": build_user_headers("unbound-seller-ops", "SellerOps"),
    "buyer_headers": build_user_headers("unbound-buyer", "Buyer"),
}


def make_seller_ops_headers(seller_account_id: str) -> dict:
    """Headers for SellerOps. Pass the SellerAccount.id: the PRD requires
    X-User-ID to equal Lot.seller_id on every seller-scoped write."""
    return build_user_headers(seller_account_id, "SellerOps")


def make_buyer_headers(buyer_account_id: str) -> dict:
    """Headers for Buyer. Pass the BuyerAccount.id: the PRD requires X-User-ID
    to equal the buyer_id of the bid, negotiation, order, appointment or claim
    being written."""
    return build_user_headers(buyer_account_id, "Buyer")


def make_platform_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_marketplace_ops_headers(user_id: str) -> dict:
    """Headers for MarketplaceOps under a named operator id - needed whenever a
    test must separate the manifest reviewer from the claim decider."""
    return build_user_headers(user_id, "MarketplaceOps")


def make_trust_safety_headers(user_id: str = TRUST_SAFETY_USER_ID) -> dict:
    return build_user_headers(user_id, "TrustSafety")
