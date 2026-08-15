"""Pre-built role headers for every role in the PRD.

All three roles use opaque identities (PRD §2.1): X-User-ID is never matched
against any entity's id, so shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "DistributorAdmin"),
    "driver_headers": build_user_headers("test-driver-1", "RouteDriver"),
    "operator_headers": build_user_headers("test-operator-1", "WarehouseOperator"),
}

# A request carrying neither X-User-ID nor X-User-Role (PRD §2.1).
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DistributorAdmin")


def make_driver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RouteDriver")


def make_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarehouseOperator")
