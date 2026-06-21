"""Pre-built role headers for every role in the PRD.

All four roles use an opaque identity model (PRD §2.1): the X-User-ID is an opaque
operator identifier that the server never compares to any entity id, and ownership
is never determined by matching X-User-ID against a stored foreign key. Authorization
is governed entirely by the role in X-User-Role. Shared constants are therefore the
canonical form for every role; there are no entity-backed roles in this domain.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "distributor_admin_headers": build_user_headers("test-admin-1", "DistributorAdmin"),
    "sales_rep_headers": build_user_headers("test-sales-1", "SalesRep"),
    "warehouse_op_headers": build_user_headers("test-warehouse-1", "WarehouseOp"),
    "credit_manager_headers": build_user_headers("test-credit-1", "CreditManager"),
}
