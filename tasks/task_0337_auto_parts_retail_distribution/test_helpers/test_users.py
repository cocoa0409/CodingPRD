"""Pre-built role headers for every role in the PRD.

All four roles use an opaque identity model (PRD §2.1): "the X-User-ID is an opaque
operator identifier that is not tied to any persisted entity", the server "does not
compare X-User-ID to any entity's id", and "there is no resource-ownership check that
ties a record to the user who created it. Authorization is determined purely by role".
Shared constants are therefore the canonical form for every role; there are no
entity-backed roles in this domain and no per-instance header builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "counter_clerk_headers": build_user_headers("test-counter-1", "CounterClerk"),
    "wholesale_rep_headers": build_user_headers("test-wholesale-1", "WholesaleRep"),
    "inventory_manager_headers": build_user_headers("test-inventory-1", "InventoryManager"),
    "warranty_admin_headers": build_user_headers("test-warranty-1", "WarrantyAdmin"),
}
