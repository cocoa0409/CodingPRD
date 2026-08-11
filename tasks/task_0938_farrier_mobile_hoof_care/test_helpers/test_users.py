"""Pre-built role headers for the six roles named in PRD section 2.1.

`Farrier` and `ClientUser` are the two entity-backed roles: their `X-User-ID`
must be the id of the acting `Farrier` / `Client` row, so ownership-gated calls
MUST use the per-instance builders below. The other four roles are opaque and
the shared constants are the canonical form for them.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — the operator id is never compared to any row's id.
    "platform_admin_headers": build_user_headers("op-admin-1", "PlatformAdmin"),
    "dispatcher_headers": build_user_headers("op-dispatcher-1", "Dispatcher"),
    "veterinarian_headers": build_user_headers("op-vet-1", "Veterinarian"),
    "billing_clerk_headers": build_user_headers("op-billing-1", "BillingClerk"),
    # Entity-backed roles — these shared constants are only safe for calls that
    # do not run an ownership check.
    "farrier_headers": build_user_headers("op-farrier-1", "Farrier"),
    "client_user_headers": build_user_headers("op-client-1", "ClientUser"),
}

NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_farrier_headers(farrier_id: str) -> dict:
    """For the entity-backed `Farrier` role: pass the acting Farrier row's id."""
    return build_user_headers(farrier_id, "Farrier")


def make_client_headers(client_id: str) -> dict:
    """For the entity-backed `ClientUser` role: pass the acting Client row's id."""
    return build_user_headers(client_id, "ClientUser")


def admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


def dispatcher_headers() -> dict:
    return TEST_USERS["dispatcher_headers"]


def vet_headers() -> dict:
    return TEST_USERS["veterinarian_headers"]


def billing_headers() -> dict:
    return TEST_USERS["billing_clerk_headers"]
