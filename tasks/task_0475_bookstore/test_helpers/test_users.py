"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Member tests that do NOT
# exercise ownership (400-on-bad-payload, 404-on-missing-resource, 403-forbidden).
TEST_USERS = {
    # entity_backed role (Member): shared constant is a fallback for non-ownership
    # tests only. Ownership-gated calls MUST use make_member_headers(member_id).
    "member_headers": build_user_headers("test-member-1", "Member"),
    # opaque roles: shared constant is the canonical form.
    "bookseller_headers": build_user_headers("test-bookseller-1", "Bookseller"),
    "inventory_manager_headers": build_user_headers("test-invmgr-1", "InventoryManager"),
    "store_admin_headers": build_user_headers("test-admin-1", "StoreAdmin"),
    # Anonymous: used for self-registration and unauthenticated-style checks.
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
}


# Per-instance builder — required for the entity_backed Member role.
def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (acting on own order/ticket/buyback/
    special order)."""
    return build_user_headers(user_id, "Member")


def make_bookseller_headers() -> dict:
    return build_user_headers("test-bookseller-1", "Bookseller")


def make_inventory_manager_headers() -> dict:
    return build_user_headers("test-invmgr-1", "InventoryManager")


def make_store_admin_headers() -> dict:
    return build_user_headers("test-admin-1", "StoreAdmin")


def make_anonymous_headers() -> dict:
    return build_user_headers("test-anon-1", "Anonymous")
