"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. Grower is entity-backed: ownership-gated calls MUST go through
# make_grower_headers() with the actual Grower.id.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "IntegratorAdmin"),
    # entity_backed: fallback for non-ownership tests only.
    "grower_headers": build_user_headers("test-grower-1", "Grower"),
    "service_tech_headers": build_user_headers("test-tech-1", "ServiceTech"),
    "livehaul_headers": build_user_headers("test-livehaul-1", "LivehaulScheduler"),
    "analyst_headers": build_user_headers("test-analyst-1", "SettlementAnalyst"),
}

# Requests without any auth headers (PRD §2.1 -> ERR_UNAUTHENTICATED).
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_grower_headers(user_id: str) -> dict:
    """For Grower (entity_backed:Grower). Pass the actual Grower.id as user_id
    whenever the call is ownership-gated (mortality reports, renewal requests,
    settlement disputes, reads of own resources)."""
    return build_user_headers(user_id, "Grower")
