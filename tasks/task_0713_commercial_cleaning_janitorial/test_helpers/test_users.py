"""Pre-built role headers for every role in the PRD (§2.1).

Four roles (SalesRep, BidEstimator, OperationsManager, PlatformAdmin) use an
opaque identity model — X-User-ID is not compared to any entity. AccountManager
is entity_backed: ownership checks compare Account.owner_user_id to X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for non-ownership tests.
TEST_USERS = {
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "SalesRep"),
    "bid_estimator_headers": build_user_headers("test-bid-estimator-1", "BidEstimator"),
    "operations_manager_headers": build_user_headers("test-ops-manager-1", "OperationsManager"),
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


# Per-instance builder — required for the entity_backed AccountManager role.
# Pass the acting account owner's id (Account.owner_user_id) when the call is
# ownership-gated.
def make_account_manager_headers(user_id: str) -> dict:
    """For AccountManager (entity_backed:Account). Pass the owning user id."""
    return build_user_headers(user_id, "AccountManager")
