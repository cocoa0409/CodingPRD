"""Pre-built role headers for every role in the PRD.

All three roles (PlatformAdmin, InventoryManager, SalesClerk) use an opaque
identity model — X-User-ID is never compared to any entity's id and no
ownership check is performed (PRD §2.1). Shared constants are therefore the
canonical form for every role; there are no entity-backed roles.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "inventory_manager_headers": build_user_headers("inv-1", "InventoryManager"),
    "sales_clerk_headers": build_user_headers("clerk-1", "SalesClerk"),
}
