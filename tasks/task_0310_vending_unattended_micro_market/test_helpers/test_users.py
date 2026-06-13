"""Pre-built role headers for every role in the PRD (Section 2.1).

Four roles: FieldOps, RouteDriver, HostManager, FinanceClerk.

- FieldOps and FinanceClerk identities are opaque operator identifiers, not tied
  to any persisted entity; the server records X-User-ID but never compares it to
  an entity id. Their shared constants are the canonical form.
- RouteDriver's X-User-ID is the id of the acting RouteDriverProfile.
- HostManager's X-User-ID is the id of the acting HostSite.
  For RouteDriver / HostManager, ownership-gated calls MUST use the per-instance
  builder with the real entity id (see make_route_driver_headers /
  make_host_manager_headers).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise
# resource ownership (e.g. 400/404/403 negative checks).
TEST_USERS = {
    "field_ops_headers": build_user_headers("test-fieldops-1", "FieldOps"),
    "finance_clerk_headers": build_user_headers("test-finance-1", "FinanceClerk"),
    # entity_backed fallbacks — only for non-ownership negative tests.
    "route_driver_headers": build_user_headers("test-driver-1", "RouteDriver"),
    "host_manager_headers": build_user_headers("test-host-1", "HostManager"),
}


def make_field_ops_headers(user_id: str = "test-fieldops-1") -> dict:
    """FieldOps (opaque identity)."""
    return build_user_headers(user_id, "FieldOps")


def make_finance_clerk_headers(user_id: str = "test-finance-1") -> dict:
    """FinanceClerk (opaque identity)."""
    return build_user_headers(user_id, "FinanceClerk")


def make_route_driver_headers(user_id: str) -> dict:
    """RouteDriver (entity_backed:RouteDriverProfile). Pass the acting driver's id
    whenever the call references that driver (open / reconcile a visit)."""
    return build_user_headers(user_id, "RouteDriver")


def make_host_manager_headers(user_id: str) -> dict:
    """HostManager (entity_backed:HostSite). Pass the acting host site's id whenever
    the call is host-scoped."""
    return build_user_headers(user_id, "HostManager")
