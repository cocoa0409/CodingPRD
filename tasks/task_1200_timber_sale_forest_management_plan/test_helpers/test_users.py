"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin, AgencyInspector)
# and for tests that do not exercise ownership (404 / 400 / role-only checks).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "inspector_headers": build_user_headers("test-inspector-1", "AgencyInspector"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership tests.
    "forester_headers": build_user_headers("test-forester-1", "Forester"),
    "landowner_headers": build_user_headers("test-landowner-1", "Landowner"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}


def make_forester_headers(user_id: str) -> dict:
    """For Forester (entity-backed). Pass the actual Forester.id whenever the
    call is ownership-gated or writes a foreign-key binding the forester."""
    return build_user_headers(user_id, "Forester")


def make_landowner_headers(user_id: str) -> dict:
    """For Landowner (entity-backed). Pass the actual Landowner.id whenever
    the call is ownership-gated (approve, accept, dispute, etc.)."""
    return build_user_headers(user_id, "Landowner")


def make_buyer_headers(user_id: str) -> dict:
    """For Buyer (entity-backed). Pass the actual Buyer.id whenever the call
    is ownership-gated (bid submission, bond posting, cure, dispute)."""
    return build_user_headers(user_id, "Buyer")


def make_contractor_headers(user_id: str) -> dict:
    """For Contractor (entity-backed). Pass the actual Contractor.id whenever
    the call is ownership-gated (start/complete harvest, record planting)."""
    return build_user_headers(user_id, "Contractor")
