"""Pre-built role headers for every role in the PRD (§2.1).

Four roles: ResidentAccount (entity-backed by ServiceAccount), Dispatcher, Driver,
Billing (the latter three are opaque operator identifiers).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque operator roles, and for ResidentAccount tests
# whose success does NOT depend on owning the subject resource (e.g., a not-owner
# rejection where X-User-ID is deliberately a different account).
TEST_USERS = {
    # Opaque operator roles — shared constant is the canonical form.
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "driver_headers": build_user_headers("driver-1", "Driver"),
    "billing_headers": build_user_headers("billing-1", "Billing"),
    # entity_backed:ServiceAccount — shared constant is a fallback for non-ownership
    # tests only. Ownership-gated resident calls MUST use make_resident_headers(id).
    "resident_headers": build_user_headers("resident-fallback-1", "ResidentAccount"),
}


def make_resident_headers(account_id: str) -> dict:
    """For ResidentAccount (entity_backed:ServiceAccount). Pass the actual
    ServiceAccount.id as X-User-ID whenever the call is ownership-gated
    (request/cancel special pickup, dispute invoice, read own billing)."""
    return build_user_headers(account_id, "ResidentAccount")
