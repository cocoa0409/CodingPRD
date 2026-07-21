"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (ShowroomAssociate, FulfillmentCoordinator,
# StoreManager) and for tests that do not exercise Designer ownership.
TEST_USERS = {
    "sm_headers": build_user_headers("test-storemanager-1", "StoreManager"),
    "associate_headers": build_user_headers("test-associate-1", "ShowroomAssociate"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "FulfillmentCoordinator"),
    # Fallback constant for Designer — used only for non-ownership tests. Ownership-gated
    # Designer calls MUST use make_designer_headers(trade_account_id) instead.
    "designer_headers": build_user_headers("test-designer-1", "Designer"),
}


def make_designer_headers(user_id: str) -> dict:
    """For Designer (entity_backed:TradeAccount). Pass the acting TradeAccount.id as
    user_id whenever the call is ownership-gated; ownership checks compare the resource's
    trade_account_id to X-User-ID (PRD §2.1)."""
    return build_user_headers(user_id, "Designer")
