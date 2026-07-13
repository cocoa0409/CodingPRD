"""Pre-built role headers for every role in the PRD (§2.1).

Three roles: AccountManager and WarehouseOps are opaque operator identifiers;
Buyer is entity-backed on Account (X-User-ID is the acting Account's id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "account_manager_headers": build_user_headers("mgr-1", "AccountManager"),
    "warehouse_headers": build_user_headers("wh-1", "WarehouseOps"),
    # Buyer shared constant: fallback for non-ownership tests only.
    "buyer_headers": build_user_headers("buyer-1", "Buyer"),
}

ACCOUNT_MANAGER_HEADERS = TEST_USERS["account_manager_headers"]
WAREHOUSE_HEADERS = TEST_USERS["warehouse_headers"]


def make_buyer_headers(account_id: str) -> dict:
    """For the Buyer role (entity-backed on Account). Pass the acting Account.id
    as X-User-ID whenever the call is ownership-gated (create/confirm/cancel/pay
    order, create/resubmit certificate, open return, add return line)."""
    return build_user_headers(account_id, "Buyer")
