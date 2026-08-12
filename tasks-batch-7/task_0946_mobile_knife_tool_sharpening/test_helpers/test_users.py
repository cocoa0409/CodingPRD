"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed: `AccountOwner` (X-User-ID is an Account id) and
`Technician` (X-User-ID is a Technician id). Ownership-gated calls MUST use the
per-instance builders below with the real row id. The other three roles are
opaque and the shared constants are the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles -- the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("admin-001", "PlatformAdmin"),
    "dispatcher_headers": build_user_headers("dispatcher-001", "Dispatcher"),
    "billing_clerk_headers": build_user_headers("clerk-001", "BillingClerk"),
    # Entity-backed roles -- fallback for non-ownership tests only
    # (for example role-gate or path-not-found probes).
    "account_owner_headers": build_user_headers("account-owner-001", "AccountOwner"),
    "technician_headers": build_user_headers("technician-001", "Technician"),
}

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


def make_account_owner_headers(account_id: str) -> dict:
    """Headers for an AccountOwner acting as the Account whose id is `account_id`."""
    return build_user_headers(account_id, "AccountOwner")


def make_technician_headers(technician_id: str) -> dict:
    """Headers for a Technician acting as the Technician row `technician_id`.

    Segregation of duties requires two distinct technicians in some flows; build
    two technician rows and call this helper once per row.
    """
    return build_user_headers(technician_id, "Technician")


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder used by role-matrix style tests."""
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
