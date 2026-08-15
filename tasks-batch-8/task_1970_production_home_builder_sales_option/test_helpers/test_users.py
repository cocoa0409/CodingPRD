"""Pre-built role headers for every role in the PRD (§2.1).

The Buyer role is entity-backed: when X-User-Role is Buyer, X-User-ID must be
the acting Buyer record's id. Use make_buyer_headers(buyer["id"]) for every
ownership-gated call; the shared "buyer_headers" entry exists only for tests
that never exercise ownership (e.g. role-denied checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-registrant-1", "Anonymous"),
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "sales_director_headers": build_user_headers("sales-director-1", "SalesDirector"),
    "sales_agent_headers": build_user_headers("sales-agent-1", "SalesAgent"),
    "construction_manager_headers": build_user_headers(
        "construction-manager-1", "ConstructionManager"
    ),
    # Fallback only: never matches a real Buyer id, so ownership-gated calls
    # would all fail. Use make_buyer_headers(buyer_id) instead.
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
}


def make_buyer_headers(user_id: str) -> dict:
    """For the entity-backed Buyer role: pass the actual Buyer.id whenever the
    call is ownership-gated (reserve, sign, cancel, selections, warranty)."""
    return build_user_headers(user_id, "Buyer")
