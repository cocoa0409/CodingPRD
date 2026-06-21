"""Pre-built role headers for every role in the PRD (section 2.1).

MarketAdmin and MarketManager are opaque operator identities — their X-User-ID
is recorded but never compared to any entity id, so the shared constants below
are the canonical form for those roles.

Vendor is entity_backed: its X-User-ID must equal the acting Vendor.id. Any
ownership-gated Vendor call MUST therefore use make_vendor_headers(vendor_id)
with the real vendor id, never the shared TEST_USERS["vendor_headers"] constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for opaque roles, and for Vendor tests that do not
# exercise ownership (e.g. an unauthenticated/forbidden probe or a 404 probe).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "MarketAdmin"),
    "manager_headers": build_user_headers("test-manager-1", "MarketManager"),
    # Fallback only — never use for an ownership-gated Vendor call.
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
}


def make_vendor_headers(vendor_id: str) -> dict:
    """Headers for the Vendor role (entity_backed:Vendor).

    Pass the real Vendor.id as X-User-ID so ownership checks (PRD 2.1) pass on
    that vendor's own applications, permits, assignments, check-ins, sales
    reports, and redemptions.
    """
    return build_user_headers(vendor_id, "Vendor")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "MarketAdmin")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "MarketManager")
