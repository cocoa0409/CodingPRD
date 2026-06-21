"""Pre-built role headers for every role in the PRD (§2.1, §4).

All three roles have opaque identity: X-User-ID is an arbitrary operator
identifier that the server never matches against any entity's id (PRD §2.1).
Shared constants are therefore the canonical form for all roles.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "inventory_manager_headers": build_user_headers("test-inv-mgr-1", "InventoryManager"),
    "purchasing_agent_headers": build_user_headers("test-purch-agent-1", "PurchasingAgent"),
    "bar_manager_headers": build_user_headers("test-bar-mgr-1", "BarManager"),
}

# Convenience aliases for direct import in fixtures.
INVENTORY_MANAGER = TEST_USERS["inventory_manager_headers"]
PURCHASING_AGENT = TEST_USERS["purchasing_agent_headers"]
BAR_MANAGER = TEST_USERS["bar_manager_headers"]


def make_unknown_role_headers(user_id: str = "test-stranger-1") -> dict:
    """Headers carrying an X-User-Role the system does not recognize.

    Used to exercise ERR_UNAUTHENTICATED (PRD §2.1)."""
    return build_user_headers(user_id, "Stranger")
