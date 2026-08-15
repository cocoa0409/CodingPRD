"""Pre-built role headers for every role in PRD §2.1.

Beneficiary and ThirdPartyBidder are entity-backed roles: their X-User-ID must
equal the acting Beneficiary.id / BidderRegistration.id whenever a call is
ownership-gated. Use the per-instance builders for those calls; the shared
constants are fallbacks for negative RBAC probes only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "trustee_admin_headers": build_user_headers("ta-1", "TrusteeAdmin"),
    "case_manager_headers": build_user_headers("cm-1", "CaseManager"),
    "auctioneer_headers": build_user_headers("auc-1", "Auctioneer"),
    # entity_backed:Beneficiary — fallback for non-ownership probes only.
    "beneficiary_headers": build_user_headers("ben-orphan-1", "Beneficiary"),
    # entity_backed:BidderRegistration — fallback for non-ownership probes only.
    "third_party_bidder_headers": build_user_headers(
        "reg-orphan-1", "ThirdPartyBidder"
    ),
}

# Headers carrying no role/id at all, and an undeclared role (PRD §2.1).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_beneficiary_headers(beneficiary_id: str) -> dict:
    """Beneficiary is entity-backed: pass the acting Beneficiary's id whenever
    the call is ownership-gated (case reads, instructions, cost advances)."""
    return build_user_headers(beneficiary_id, "Beneficiary")


def make_third_party_bidder_headers(registration_id: str) -> dict:
    """ThirdPartyBidder is entity-backed: pass the acting BidderRegistration's
    id whenever placing a bid or reading the registration."""
    return build_user_headers(registration_id, "ThirdPartyBidder")


def make_case_manager_headers(user_id: str) -> dict:
    """CaseManager identity is opaque, but it is recorded as a claim's
    filed_by_user_id and compared at review time (segregation of duties)."""
    return build_user_headers(user_id, "CaseManager")
