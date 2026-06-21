"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque BrokerageAdmin role, and for tests that do
# not exercise broker ownership (e.g. role-forbidden 403s, missing-resource 404s).
# ListingBroker / TenantBroker are entity_backed:Broker — their shared constant is a
# fallback only; ownership-gated calls MUST use make_*_headers(broker_id) below.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-operator-1", "BrokerageAdmin"),
    "listing_broker_headers": build_user_headers("test-listing-broker-1", "ListingBroker"),
    "tenant_broker_headers": build_user_headers("test-tenant-broker-1", "TenantBroker"),
}


def make_admin_headers(user_id: str = "admin-operator-1") -> dict:
    """BrokerageAdmin is opaque: X-User-ID is not tied to any persisted entity."""
    return build_user_headers(user_id, "BrokerageAdmin")


def make_listing_broker_headers(user_id: str) -> dict:
    """For ListingBroker (entity_backed:Broker). Pass the acting Broker.id as user_id
    so ownership checks on Property/Space/Listing/Deal.listing_broker_id pass."""
    return build_user_headers(user_id, "ListingBroker")


def make_tenant_broker_headers(user_id: str) -> dict:
    """For TenantBroker (entity_backed:Broker). Pass the acting Broker.id as user_id
    so ownership checks on Requirement/Tour/Deal.procuring_broker_id pass."""
    return build_user_headers(user_id, "TenantBroker")
