"""Pre-built role headers for every role in the PRD.

Every role in this API is an opaque identity: X-User-ID is not tied to any
persisted entity. The single exception in practice is the claim-payment
segregation-of-duties check, which compares the payer's X-User-ID against a
previously recorded decided_by_user_id — tests exercise it by building
headers with distinct user ids via the make_* builders.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical form for this API's opaque roles.
TEST_USERS = {
    "feedyard_manager_headers": build_user_headers("test-fym-1", "FeedyardManager"),
    "feed_manager_headers": build_user_headers("test-fm-1", "FeedManager"),
    "cattle_health_tech_headers": build_user_headers("test-cht-1", "CattleHealthTech"),
    "risk_manager_headers": build_user_headers("test-rm-1", "RiskManager"),
    "claims_adjuster_headers": build_user_headers("test-adj-1", "ClaimsAdjuster"),
    "claims_treasurer_headers": build_user_headers("test-tre-1", "ClaimsTreasurer"),
    "billing_clerk_headers": build_user_headers("test-bc-1", "BillingClerk"),
    # A convenience alias for read-only calls under the PRD's "Any" shorthand.
    "any_headers": build_user_headers("test-fym-1", "FeedyardManager"),
}


def make_feedyard_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FeedyardManager")


def make_feed_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FeedManager")


def make_cattle_health_tech_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CattleHealthTech")


def make_risk_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RiskManager")


def make_claims_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_claims_treasurer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsTreasurer")


def make_billing_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingClerk")
