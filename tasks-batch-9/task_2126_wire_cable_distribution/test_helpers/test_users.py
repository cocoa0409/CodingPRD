"""Pre-built role headers for every operator role in the PRD (§2.1).

`PlatformAdmin`, `SalesRep` and `CreditManager` carry an opaque `X-User-ID`
that the server never compares to any entity id, so a shared constant is the
canonical form for those three.

`BranchOps` carries the acting `Branch` id, `Driver` carries the acting
`Truck` id and `Customer` carries the acting `Customer` id, so every
ownership-gated call must build its headers from the real entity id with the
matching `make_*_headers` builder.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for tests that do not
# exercise an ownership check.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("adm-1", "PlatformAdmin"),
    "sales_rep_headers": build_user_headers("rep-1", "SalesRep"),
    "sales_rep_2_headers": build_user_headers("rep-2", "SalesRep"),
    "credit_manager_headers": build_user_headers("cm-1", "CreditManager"),
    # Fallbacks for non-ownership tests only (e.g. 404 / 422 probes).
    "branch_ops_headers": build_user_headers("branch-ops-unowned", "BranchOps"),
    "driver_headers": build_user_headers("driver-unowned", "Driver"),
    "customer_headers": build_user_headers("customer-unowned", "Customer"),
}


def make_platform_admin_headers(user_id: str = "adm-1") -> dict:
    """PlatformAdmin acts under an opaque operator identifier."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_sales_rep_headers(user_id: str = "rep-1") -> dict:
    """SalesRep acts under an opaque operator identifier; the server records
    it as created_by_user_id / issued_by_user_id and compares those two
    against each other for segregation of duties."""
    return build_user_headers(user_id, "SalesRep")


def make_credit_manager_headers(user_id: str = "cm-1") -> dict:
    """CreditManager acts under an opaque operator identifier."""
    return build_user_headers(user_id, "CreditManager")


def make_branch_ops_headers(branch_id: str) -> dict:
    """BranchOps carries the acting Branch id as X-User-ID. Pass the real
    Branch id whenever the call is ownership-gated."""
    return build_user_headers(branch_id, "BranchOps")


def make_driver_headers(truck_id: str) -> dict:
    """Driver carries the acting Truck id as X-User-ID. Pass the real Truck
    id whenever the call is ownership-gated."""
    return build_user_headers(truck_id, "Driver")


def make_customer_headers(customer_id: str) -> dict:
    """Customer carries the acting Customer id as X-User-ID."""
    return build_user_headers(customer_id, "Customer")
