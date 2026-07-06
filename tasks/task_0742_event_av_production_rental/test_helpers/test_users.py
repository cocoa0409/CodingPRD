"""Pre-built role headers for every role in the PRD (§2.1).

Three roles (AccountManager, WarehouseManager, CrewChief) are opaque operator
identities not bound to any stored entity — the shared constants below are the
canonical form for them.

The Client role is entity_backed:Customer. Ownership checks compare X-User-ID to
the order's customer_id, so ownership-gated Client calls MUST use
make_client_headers(customer_id) with the real Customer.id — never the shared
constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for the three opaque operator roles, and usable by
# Client tests that do NOT exercise ownership (e.g., forbidden/unauthenticated cases).
TEST_USERS = {
    "account_manager_headers": build_user_headers("test-am-1", "AccountManager"),
    "warehouse_manager_headers": build_user_headers("test-wm-1", "WarehouseManager"),
    "crew_chief_headers": build_user_headers("test-cc-1", "CrewChief"),
    # Fallback only — real Client calls must be built per-customer with make_client_headers.
    "client_headers": build_user_headers("test-client-1", "Client"),
}


def make_client_headers(customer_id: str) -> dict:
    """For the entity_backed Client role (PRD §2.1). Pass the acting Customer.id as
    X-User-ID whenever the call is ownership-gated (COI submission, own-order reads)."""
    return build_user_headers(customer_id, "Client")


def make_account_manager_headers(user_id: str = "test-am-1") -> dict:
    return build_user_headers(user_id, "AccountManager")


def make_warehouse_manager_headers(user_id: str = "test-wm-1") -> dict:
    return build_user_headers(user_id, "WarehouseManager")


def make_crew_chief_headers(user_id: str = "test-cc-1") -> dict:
    return build_user_headers(user_id, "CrewChief")
