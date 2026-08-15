"""Pre-built role headers for every role in the PRD (section 2.1).

OemNetworkAdmin / OemSalesOps / OemAuditor are opaque roles: X-User-ID is an
operator identifier never compared to any entity id, so the shared constants
are their canonical form.

DealerUser is entity-backed: X-User-ID IS the acting Dealer's id. The shared
constant is a fallback for tests that do not exercise ownership; any
ownership-gated call MUST use make_dealer_user_headers(dealer["id"]) so the
header matches a real Dealer id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "oem_admin_headers": build_user_headers("test-admin-1", "OemNetworkAdmin"),
    "sales_ops_headers": build_user_headers("test-salesops-1", "OemSalesOps"),
    "auditor_headers": build_user_headers("test-auditor-1", "OemAuditor"),
    # Fallback for non-ownership DealerUser scenarios only.
    "dealer_user_headers": build_user_headers("test-dealer-1", "DealerUser"),
}


def make_dealer_user_headers(user_id: str) -> dict:
    """For DealerUser (entity-backed: Dealer). Pass the actual Dealer.id as
    user_id whenever the call is ownership-gated (unit sales, claims,
    returns, certifications, lead responses, disputes)."""
    return build_user_headers(user_id, "DealerUser")
