"""Pre-built role headers for every role in the PRD.

Producer is entity_backed:Producer (X-User-ID == the acting Producer.id).
MarketManager is entity_backed:FarmersMarket (X-User-ID == the managed FarmersMarket.id).
HealthInspector and HealthAdmin are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# resource ownership (400-on-bad-payload, 404-on-missing, or opaque-role calls).
TEST_USERS = {
    "producer_headers": build_user_headers("test-producer-1", "Producer"),
    "inspector_headers": build_user_headers("test-inspector-1", "HealthInspector"),
    "market_manager_headers": build_user_headers("test-market-1", "MarketManager"),
    "admin_headers": build_user_headers("test-admin-1", "HealthAdmin"),
}


# Per-instance builders — required for every entity_backed role.
def make_producer_headers(user_id: str) -> dict:
    """For Producer (entity_backed:Producer). Pass the actual Producer.id whenever
    the call is ownership-gated (products, permits, manifests, sales, verify)."""
    return build_user_headers(user_id, "Producer")


def make_market_manager_headers(user_id: str) -> dict:
    """For MarketManager (entity_backed:FarmersMarket). Pass the actual
    FarmersMarket.id as user_id for approve/reject/check-in on that market."""
    return build_user_headers(user_id, "MarketManager")


def make_inspector_headers(user_id: str) -> dict:
    """For HealthInspector (opaque). Distinct user_id values let SoD tests
    file and review a complaint as different users."""
    return build_user_headers(user_id, "HealthInspector")


def make_admin_headers(user_id: str) -> dict:
    """For HealthAdmin (opaque)."""
    return build_user_headers(user_id, "HealthAdmin")
