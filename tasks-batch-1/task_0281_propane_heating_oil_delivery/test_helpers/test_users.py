"""Pre-built role headers for every role in the PRD (§2.1).

Four operator roles (AccountManager, Dispatcher, Driver, Inspector) and the
System automation role are opaque: their X-User-ID is never compared to any
entity id, so the shared constants are the canonical form.

The Customer role is entity_backed:Account — its X-User-ID must equal the acting
Account's id. For ownership-gated calls, build per-instance headers with
make_customer_headers(account_id); the shared constant is only safe for tests
that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "system_headers": build_user_headers("test-system-1", "System"),
    # Customer shared constant: fallback for non-ownership tests only (e.g. forbidden /
    # not-owner negative tests). Ownership-positive calls MUST use make_customer_headers.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(account_id: str) -> dict:
    """For the Customer role (entity_backed:Account). Pass the acting Account.id as
    X-User-ID whenever the call is ownership-gated (create/cancel own order, own
    budget enrollment, reads scoped to own account)."""
    return build_user_headers(account_id, "Customer")
