"""Pre-built role headers for the four roles the PRD declares (§2.1).

`Baker` and `Customer` are entity-backed: `X-User-ID` must be the id of the
acting Baker / Customer, so ownership-gated calls MUST use the per-instance
builders below. `PlatformAdmin` and `HealthInspector` carry opaque identifiers
that the server never compares to any entity id, so the shared constants are
the canonical form for those two.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "platform_admin_headers": build_user_headers("admin-operator-1", "PlatformAdmin"),
    "health_inspector_headers": build_user_headers("inspector-7", "HealthInspector"),
    # Entity-backed roles — these shared constants are a fallback for tests that
    # do not exercise ownership at all (e.g. a 404 on a missing resource).
    "baker_headers": build_user_headers("not-a-real-baker-id", "Baker"),
    "customer_headers": build_user_headers("not-a-real-customer-id", "Customer"),
}

ADMIN = TEST_USERS["platform_admin_headers"]
INSPECTOR = TEST_USERS["health_inspector_headers"]


def make_baker_headers(baker_id: str) -> dict:
    """For the Baker role: pass the acting Baker's own id."""
    return build_user_headers(baker_id, "Baker")


def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role: pass the acting Customer's own id."""
    return build_user_headers(customer_id, "Customer")


def make_admin_headers(user_id: str = "admin-operator-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_inspector_headers(user_id: str = "inspector-7") -> dict:
    return build_user_headers(user_id, "HealthInspector")


def make_headers(role: str, user_id: str) -> dict:
    return build_user_headers(user_id, role)
