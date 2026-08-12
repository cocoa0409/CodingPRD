"""Pre-built role headers for the nine barn roles.

Six roles are operator identities whose X-User-ID is an opaque string the server
never compares to a resource id: BarnAdmin, YardOperator, Auctioneer, RingClerk,
SettlementClerk, Inspector.

Three roles are party identities whose X-User-ID is the id of the acting Party:
Consignor, Buyer, Carrier. Every ownership-gated call for those three MUST be
built with the per-instance builders below, passing the real Party id.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Operator identities — the shared constant is the canonical form.
    "barn_admin_headers": build_user_headers("op-barn-admin-1", "BarnAdmin"),
    "yard_operator_headers": build_user_headers("op-yard-operator-1", "YardOperator"),
    "auctioneer_headers": build_user_headers("op-auctioneer-1", "Auctioneer"),
    "ring_clerk_headers": build_user_headers("op-ring-clerk-1", "RingClerk"),
    "settlement_clerk_headers": build_user_headers("op-settlement-clerk-1", "SettlementClerk"),
    "inspector_headers": build_user_headers("op-inspector-1", "Inspector"),
    # Party identities — these shared constants are ONLY safe for tests that do
    # not exercise ownership (for example a 401/403 probe on a missing header).
    "consignor_headers": build_user_headers("party-consignor-placeholder", "Consignor"),
    "buyer_headers": build_user_headers("party-buyer-placeholder", "Buyer"),
    "carrier_headers": build_user_headers("party-carrier-placeholder", "Carrier"),
}


def make_consignor_headers(party_id: str) -> dict:
    """Headers for a Consignor acting on their own consignment."""
    return build_user_headers(party_id, "Consignor")


def make_buyer_headers(party_id: str) -> dict:
    """Headers for a Buyer acting through their own registration."""
    return build_user_headers(party_id, "Buyer")


def make_carrier_headers(party_id: str) -> dict:
    """Headers for a Carrier acting on their own load manifest."""
    return build_user_headers(party_id, "Carrier")


BARN_ADMIN = TEST_USERS["barn_admin_headers"]
YARD_OPERATOR = TEST_USERS["yard_operator_headers"]
AUCTIONEER = TEST_USERS["auctioneer_headers"]
RING_CLERK = TEST_USERS["ring_clerk_headers"]
SETTLEMENT_CLERK = TEST_USERS["settlement_clerk_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
