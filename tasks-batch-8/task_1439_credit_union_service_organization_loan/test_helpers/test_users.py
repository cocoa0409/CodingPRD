"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (NetworkAdmin, RegulatorUser), and for
# entity-backed roles in tests that do NOT exercise ownership (e.g. RBAC denials).
TEST_USERS = {
    "network_admin_headers": build_user_headers("test-admin-1", "NetworkAdmin"),
    "regulator_headers": build_user_headers("reg-1", "RegulatorUser"),
    "treasury_headers": build_user_headers("test-treasury-1", "TreasuryUser"),
    "cuso_officer_headers": build_user_headers("test-cuso-officer-1", "CUSOOfficer"),
    "originator_headers": build_user_headers("test-originator-1", "OriginatorUser"),
    "buyer_headers": build_user_headers("test-buyer-1", "BuyerUser"),
}


# Per-instance builders — required for every entity-backed role (PRD §2.1:
# TreasuryUser/CUSOOfficer/OriginatorUser/BuyerUser X-User-ID IS the entity id).
def make_treasury_headers(credit_union_id: str) -> dict:
    """TreasuryUser headers bound to a specific CreditUnion id (ownership-gated calls)."""
    return build_user_headers(credit_union_id, "TreasuryUser")


def make_cuso_officer_headers(cuso_id: str) -> dict:
    """CUSOOfficer headers bound to a specific CUSO id (ownership-gated calls)."""
    return build_user_headers(cuso_id, "CUSOOfficer")


def make_originator_headers(credit_union_id: str) -> dict:
    """OriginatorUser headers bound to a specific CreditUnion id (agreement originator)."""
    return build_user_headers(credit_union_id, "OriginatorUser")


def make_buyer_headers(credit_union_id: str) -> dict:
    """BuyerUser headers bound to a specific CreditUnion id (certificate buyer)."""
    return build_user_headers(credit_union_id, "BuyerUser")


def make_regulator_headers(user_id: str) -> dict:
    """RegulatorUser headers with a chosen operator id (segregation-of-duties tests)."""
    return build_user_headers(user_id, "RegulatorUser")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """NetworkAdmin headers with a chosen operator id."""
    return build_user_headers(user_id, "NetworkAdmin")
