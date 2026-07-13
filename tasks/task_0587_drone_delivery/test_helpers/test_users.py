"""Pre-built role headers for every role in the PRD.

`Customer` is the only entity-backed role: its `X-User-ID` is the id of the acting
Customer record, so ownership-gated calls MUST use `make_customer_headers(customer["id"])`.
The other four roles carry an opaque operator identifier that the server never compares
to an entity id, so the shared constants below are the canonical form for them.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used throughout the suite.
OPERATOR_ID = "op-1"
DIRECTOR_ID = "fd-1"
TECH_ID = "mt-1"
ADMIN_ID = "admin-1"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(ADMIN_ID, "PlatformAdmin"),
    "dispatch_operator_headers": build_user_headers(OPERATOR_ID, "DispatchOperator"),
    "flight_director_headers": build_user_headers(DIRECTOR_ID, "FlightDirector"),
    "maintenance_tech_headers": build_user_headers(TECH_ID, "MaintenanceTech"),
    # Entity-backed role — this fallback is only safe for tests that never exercise
    # order ownership (e.g. role-denial checks). Ownership-gated calls must use
    # make_customer_headers(<the real Customer id>).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role (X-User-ID is the acting Customer's id).

    Pass the actual Customer's `id` whenever the call is ownership-gated
    (order intake and order cancellation).
    """
    return build_user_headers(customer_id, "Customer")


def make_dispatch_operator_headers(user_id: str) -> dict:
    """DispatchOperator acting under a specific opaque identifier."""
    return build_user_headers(user_id, "DispatchOperator")


def make_flight_director_headers(user_id: str) -> dict:
    """FlightDirector acting under a specific opaque identifier (segregation of duties)."""
    return build_user_headers(user_id, "FlightDirector")


def make_maintenance_tech_headers(user_id: str) -> dict:
    """MaintenanceTech acting under a specific opaque identifier."""
    return build_user_headers(user_id, "MaintenanceTech")


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin acting under a specific opaque identifier."""
    return build_user_headers(user_id, "PlatformAdmin")
