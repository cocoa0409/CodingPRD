"""Pre-built role headers for every role in the PRD.

PlatformAdmin, LocationOperator, and BillingAdmin are opaque operator
identities — the server never compares their X-User-ID to any entity id, so
shared constants are the canonical form for them.

AccountHolder is the only entity-backed role: its X-User-ID must equal the
owning Account.id for ownership-gated calls. Use make_account_holder_headers()
with the real account id; the shared constant is a fallback only for tests
whose success does NOT depend on ownership (e.g. 400/404/403 paths).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("op-platform-admin", "PlatformAdmin"),
    "location_operator_headers": build_user_headers("op-location-operator", "LocationOperator"),
    "billing_admin_headers": build_user_headers("op-billing-admin", "BillingAdmin"),
    # Fallback only — real ownership-gated calls must use make_account_holder_headers().
    "account_holder_headers": build_user_headers("ah-fallback", "AccountHolder"),
}


def make_account_holder_headers(account_id: str) -> dict:
    """For AccountHolder (entity-backed:Account). Pass the actual Account.id as
    X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(account_id, "AccountHolder")
