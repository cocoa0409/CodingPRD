"""Pre-built role headers for every role in the PRD.

Four operator roles (SalesAssociate, RentalClerk, AccountsManager,
InventoryManager) have opaque identity — the shared constant is the canonical
form. The fifth role, Contractor, is entity-backed: its X-User-ID must be the
acting ContractorAccount.id whenever an ownership check applies, so a
per-instance builder is provided.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque operator roles, plus the Contractor fallback used
# only for non-ownership tests (e.g. 401/403/404/422 negative paths).
TEST_USERS = {
    "sales_associate_headers": build_user_headers("op-sales-1", "SalesAssociate"),
    "rental_clerk_headers": build_user_headers("op-rental-1", "RentalClerk"),
    "accounts_manager_headers": build_user_headers("op-accounts-1", "AccountsManager"),
    "inventory_manager_headers": build_user_headers("op-inventory-1", "InventoryManager"),
    # Contractor shared constant: an opaque id that owns no entity — only safe
    # for tests that do NOT exercise ownership (it will fail any ownership gate).
    "contractor_headers": build_user_headers("contractor-unowned-1", "Contractor"),
}


# Per-instance builder — required for the entity-backed Contractor role.
def make_contractor_headers(account_id: str) -> dict:
    """For the Contractor role (entity_backed:ContractorAccount). Pass the
    actual ContractorAccount.id as the X-User-ID whenever the call is
    ownership-gated (special-order confirm / request-revision / cancel, and
    reads of the contractor's own account)."""
    return build_user_headers(account_id, "Contractor")


# Convenience aliases used throughout fixtures and tests.
SALES = TEST_USERS["sales_associate_headers"]
RENTAL = TEST_USERS["rental_clerk_headers"]
ACCOUNTS = TEST_USERS["accounts_manager_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]
