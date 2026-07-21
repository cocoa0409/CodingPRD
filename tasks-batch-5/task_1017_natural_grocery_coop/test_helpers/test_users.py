"""Pre-built role headers for every role in the PRD (§2.1).

Five roles are operator roles whose identity is opaque (CoopAdmin, FinanceManager,
InventoryManager, Cashier, BoardAdmin): X-User-ID is an operator identifier not tied
to any persisted entity, so the shared constant is the canonical form for them.

The Member role is entity_backed: when X-User-Role is Member, X-User-ID is the id of
the acting Member, and any operation acting on that member's own behalf (casting a
board vote) compares the referenced member to X-User-ID. Use make_member_headers(id)
with the actual Member.id for those ownership-gated calls.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque operator roles — shared constant is canonical
    "coop_admin_headers": build_user_headers("test-coopadmin-1", "CoopAdmin"),
    "finance_manager_headers": build_user_headers("test-finance-1", "FinanceManager"),
    "inventory_manager_headers": build_user_headers("test-inventory-1", "InventoryManager"),
    "cashier_headers": build_user_headers("test-cashier-1", "Cashier"),
    "board_admin_headers": build_user_headers("test-boardadmin-1", "BoardAdmin"),
    # entity_backed Member fallback — only for non-ownership tests (404 / bad payload).
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(member_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the acting Member.id as
    X-User-ID so that a board vote's member_id == X-User-ID ownership check passes."""
    return build_user_headers(member_id, "Member")
