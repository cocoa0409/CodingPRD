"""Pre-built role headers for every role in the PRD (§2.1).

Three roles: Seller (entity-backed by a Seller record), PlatformReviewer
(opaque operator id), and PlatformFinance (opaque operator id).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise
# Seller ownership (e.g. 400-on-bad-payload, 404-on-missing-resource).
#
# For the Seller role the shared constant uses a placeholder id that will NOT
# equal any real Seller.id; it is therefore only valid for non-ownership tests.
TEST_USERS = {
    # Seller (entity_backed:Seller) — fallback for non-ownership tests only.
    "seller_headers": build_user_headers("test-seller-placeholder", "Seller"),
    # PlatformReviewer (opaque) — shared constant is the canonical form.
    "reviewer_headers": build_user_headers("reviewer-1", "PlatformReviewer"),
    # PlatformFinance (opaque) — shared constant is the canonical form.
    "finance_headers": build_user_headers("finance-1", "PlatformFinance"),
    # A second distinct PlatformFinance operator (for segregation-of-duties:
    # different from the reviewer who approved KYC).
    "finance2_headers": build_user_headers("finance-2", "PlatformFinance"),
}


def make_seller_headers(user_id: str) -> dict:
    """For the Seller role (entity_backed:Seller). Pass the actual Seller.id as
    user_id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Seller")


def make_reviewer_headers(user_id: str = "reviewer-1") -> dict:
    """For PlatformReviewer (opaque). The id is recorded into kyc_reviewer_id on
    KYC decision (PRD §2.1); pass a specific id to control segregation-of-duties
    scenarios."""
    return build_user_headers(user_id, "PlatformReviewer")


def make_finance_headers(user_id: str = "finance-1") -> dict:
    """For PlatformFinance (opaque). The id is recorded into finance_user_id on
    payout release (PRD §2.1); pass a specific id to control segregation-of-duties
    scenarios."""
    return build_user_headers(user_id, "PlatformFinance")
