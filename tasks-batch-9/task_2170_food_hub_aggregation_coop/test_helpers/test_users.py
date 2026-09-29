"""Pre-built role headers for every cooperative role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    APPROVER_USER_ID,
    BOARD_DIRECTOR_USER_ID,
    CLAIMS_OFFICER_USER_ID,
    HUB_ADMIN_USER_ID,
    VERIFIER_USER_ID,
)

# Shared constants.  Safe for the three opaque roles, and for tests whose
# outcome does not depend on the caller owning the subject resource.
TEST_USERS = {
    "hub_admin_headers": build_user_headers(HUB_ADMIN_USER_ID, "HubAdmin"),
    "compliance_officer_headers": build_user_headers(VERIFIER_USER_ID, "ComplianceOfficer"),
    "approver_headers": build_user_headers(APPROVER_USER_ID, "ComplianceOfficer"),
    "claims_officer_headers": build_user_headers(CLAIMS_OFFICER_USER_ID, "ComplianceOfficer"),
    "board_director_headers": build_user_headers(BOARD_DIRECTOR_USER_ID, "BoardDirector"),
    # Entity-backed roles: these shared constants are only a fallback for
    # tests that never exercise an ownership check.
    "producer_headers": build_user_headers("test-producer-1", "Producer"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
}


def make_producer_headers(producer_id: str) -> dict:
    """Headers for the Producer role.  X-User-ID must be the acting Producer id."""
    return build_user_headers(producer_id, "Producer")


def make_buyer_headers(buyer_id: str) -> dict:
    """Headers for the Buyer role.  X-User-ID must be the acting Buyer id."""
    return build_user_headers(buyer_id, "Buyer")


def make_hub_admin_headers(user_id: str = HUB_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "HubAdmin")


def make_compliance_officer_headers(user_id: str = VERIFIER_USER_ID) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_board_director_headers(user_id: str = BOARD_DIRECTOR_USER_ID) -> dict:
    return build_user_headers(user_id, "BoardDirector")


__all__ = [
    "TEST_USERS",
    "make_producer_headers",
    "make_buyer_headers",
    "make_hub_admin_headers",
    "make_compliance_officer_headers",
    "make_board_director_headers",
]
