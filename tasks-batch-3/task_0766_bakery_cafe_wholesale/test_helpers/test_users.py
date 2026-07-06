"""Pre-built role headers for every role in the PRD.

Manager, Baker, Cashier and Driver carry opaque X-User-ID values. WholesaleClient
is entity-backed by a WholesaleAccount: ownership checks compare a resource's
wholesale_account_id to X-User-ID, so a WholesaleClient acting on its own resource
MUST use make_wholesale_client_headers(account_id) with the real account id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise ownership.
TEST_USERS = {
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    "baker_headers": build_user_headers("test-baker-1", "Baker"),
    "cashier_headers": build_user_headers("test-cashier-1", "Cashier"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    # Fallback only for non-ownership WholesaleClient tests (never for owned-resource calls).
    "wholesale_client_headers": build_user_headers("test-wholesale-1", "WholesaleClient"),
}


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "Manager")


def make_wholesale_client_headers(account_id: str) -> dict:
    """For WholesaleClient (entity_backed:WholesaleAccount). Pass the acting
    WholesaleAccount.id as X-User-ID for any ownership-gated call."""
    return build_user_headers(account_id, "WholesaleClient")
