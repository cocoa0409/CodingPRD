"""Pre-built role headers for every role in the PRD (§2.1).

TerritoryManager, MarketAdministrator, and QualityInspector are opaque roles:
their X-User-ID is an operator identifier never compared to any entity id.

DistributorOwner, RouteDriver, and StoreReceiver are entity-backed: X-User-ID
must equal the acting Distributor / Driver / Store id whenever the call is
ownership-gated. Use the per-instance builders with the real entity id for
those calls; the shared constants exist only for tests whose outcome does not
depend on ownership (400-on-bad-payload, 404 sweeps, RBAC role denials).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    "territory_manager_headers": build_user_headers("test-tm-1", "TerritoryManager"),
    "market_admin_headers": build_user_headers("test-ma-1", "MarketAdministrator"),
    "quality_inspector_headers": build_user_headers("test-qi-1", "QualityInspector"),
    # entity_backed roles: fallback constants for non-ownership tests only.
    "distributor_owner_headers": build_user_headers("test-owner-1", "DistributorOwner"),
    "route_driver_headers": build_user_headers("test-driver-1", "RouteDriver"),
    "store_receiver_headers": build_user_headers("test-receiver-1", "StoreReceiver"),
}


def make_territory_manager_headers(user_id: str = "test-tm-1") -> dict:
    return build_user_headers(user_id, "TerritoryManager")


def make_market_admin_headers(user_id: str = "test-ma-1") -> dict:
    return build_user_headers(user_id, "MarketAdministrator")


def make_quality_inspector_headers(user_id: str = "test-qi-1") -> dict:
    return build_user_headers(user_id, "QualityInspector")


def make_distributor_owner_headers(distributor_id: str) -> dict:
    """DistributorOwner is entity_backed:Distributor — pass the acting
    Distributor's id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(distributor_id, "DistributorOwner")


def make_driver_headers(driver_id: str) -> dict:
    """RouteDriver is entity_backed:Driver — pass the acting Driver's id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(driver_id, "RouteDriver")


def make_store_receiver_headers(store_id: str) -> dict:
    """StoreReceiver is entity_backed:Store — pass the acting Store's id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(store_id, "StoreReceiver")
