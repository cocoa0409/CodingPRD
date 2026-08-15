"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constants are the canonical form.
    "ad_ops_headers": build_user_headers("test-adops-1", "AdOps"),
    "finance_headers": build_user_headers("test-finance-1", "Finance"),
    "ingestion_headers": build_user_headers("test-ingestion-1", "Ingestion"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "advertiser_headers": build_user_headers("test-advertiser-1", "Advertiser"),
    "agency_headers": build_user_headers("test-agency-1", "Agency"),
    "show_producer_headers": build_user_headers("test-producer-1", "ShowProducer"),
}


# Per-instance builders — required for the entity_backed roles.
def make_advertiser_headers(user_id: str) -> dict:
    """For Advertiser (entity_backed:Advertiser). Pass the actual Advertiser.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Advertiser")


def make_agency_headers(user_id: str) -> dict:
    """For Agency (entity_backed:Agency). Pass the actual Agency.id as user_id
    whenever the call is representation-gated."""
    return build_user_headers(user_id, "Agency")


def make_show_producer_headers(user_id: str) -> dict:
    """For ShowProducer (entity_backed:Show). Pass the actual Show.id as user_id
    whenever the call is show-scope-gated."""
    return build_user_headers(user_id, "ShowProducer")
