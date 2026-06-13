"""Pre-built role headers for every role in the PRD.

Two roles (MonitoringOperator, Administrator) carry opaque identities — a
shared constant is the canonical form. The Subscriber role is entity-backed
by an Account: ownership-gated calls (arm, disarm, request/withdraw
cancellation, pay fine) compare X-User-ID against the resource's owning
Account.id, so those calls MUST use make_subscriber_headers(account_id) with
the real account id. The shared subscriber constant is only safe for tests
that do not exercise ownership (e.g. forbidden-role or unauthenticated checks).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "admin_headers": build_user_headers("test-admin-1", "Administrator"),
    "operator_headers": build_user_headers("test-operator-1", "MonitoringOperator"),
    # Entity-backed Subscriber — shared constant is a non-ownership fallback only.
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
}


def make_subscriber_headers(account_id: str) -> dict:
    """Headers for a Subscriber (identity entity_backed:Account).

    Pass the actual owning Account.id as user_id whenever the call is
    ownership-gated; the server compares X-User-ID to the resource's owning
    Account.id.
    """
    return build_user_headers(account_id, "Subscriber")


def make_operator_headers(user_id: str = "test-operator-1") -> dict:
    """Headers for a MonitoringOperator (opaque identity)."""
    return build_user_headers(user_id, "MonitoringOperator")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """Headers for an Administrator (opaque identity)."""
    return build_user_headers(user_id, "Administrator")
