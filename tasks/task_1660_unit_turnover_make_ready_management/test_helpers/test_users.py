"""Pre-built role headers for every role in the PRD (§2.1).

The Vendor role is entity-backed: ownership checks compare the assignment's
vendor_id against X-User-ID, so vendor calls acting on their own assignments
MUST go through make_vendor_headers(vendor["id"]). The shared
"vendor_headers" constant is a fallback for tests that never exercise
ownership (e.g., RBAC denials on non-vendor endpoints).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "regional_manager_headers": build_user_headers("test-rm-1", "RegionalManager"),
    "property_manager_headers": build_user_headers("test-pm-1", "PropertyManager"),
    "turn_coordinator_headers": build_user_headers("test-tc-1", "TurnCoordinator"),
    # entity_backed:Vendor — fallback only; use make_vendor_headers for
    # ownership-gated vendor actions (accept / decline / complete).
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
    "inspector_headers": build_user_headers("test-insp-1", "Inspector"),
    "platform_admin_headers": build_user_headers("test-pa-1", "PlatformAdmin"),
}

# No authentication headers at all (PRD §2.8 check 1).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}

# A role outside the declared set (PRD §2.1).
UNKNOWN_ROLE_HEADERS = {
    "X-User-ID": "test-nobody-1",
    "X-User-Role": "SuperIntendent",
    "Content-Type": "application/json",
}


def make_vendor_headers(vendor_id: str) -> dict:
    """For the entity-backed Vendor role. Pass the actual Vendor.id whenever
    the call is ownership-gated (accept / decline / complete)."""
    return build_user_headers(vendor_id, "Vendor")
