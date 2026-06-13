"""Pre-built role headers for every role in the PRD (§2.1).

Roles LotOperator, PoliceOfficer, Claimant, AuctionOfficial carry an OPAQUE
X-User-ID not tied to any entity. TowProvider is entity_backed: its X-User-ID
must equal the acting provider's id whenever an ownership-gated call (accept /
decline a rotation offer) is made.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# provider ownership (e.g. 403/404 checks, reads, lot operations).
TEST_USERS = {
    "lot_operator_headers": build_user_headers("operator-1", "LotOperator"),
    "police_officer_headers": build_user_headers("police-1", "PoliceOfficer"),
    "claimant_headers": build_user_headers("claimant-1", "Claimant"),
    "auction_official_headers": build_user_headers("auction-1", "AuctionOfficial"),
    # TowProvider shared constant: fallback for NON-ownership tests only
    # (its X-User-ID equals no real provider id, so any ownership check rejects it).
    "tow_provider_headers": build_user_headers("provider-shared", "TowProvider"),
}


def make_lot_operator_headers(user_id: str) -> dict:
    """LotOperator with an explicit X-User-ID (used for segregation-of-duties scenarios)."""
    return build_user_headers(user_id, "LotOperator")


def make_claimant_headers(user_id: str) -> dict:
    """Claimant with an explicit X-User-ID (filer identity for fee waivers)."""
    return build_user_headers(user_id, "Claimant")


def make_tow_provider_headers(provider_id: str) -> dict:
    """For TowProvider (entity_backed:TowProvider). Pass the actual TowProvider.id
    as user_id whenever the call is ownership-gated (accept / decline)."""
    return build_user_headers(provider_id, "TowProvider")
