"""Pre-built role headers for every role the PRD recognises (PRD 2.1).

FleetAdmin, Inspector and ChargebackApprover carry an opaque operator
identifier that the server never compares to any entity id, so the shared
constants below are the canonical form for them.

BranchManager and Customer are entity-backed: X-User-ID is the id of the
acting Branch / Customer, so ownership-gated calls MUST use the per-instance
builders and pass the real entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identities.
    "fleet_admin_headers": build_user_headers("admin-1", "FleetAdmin"),
    "inspector_headers": build_user_headers("insp-1", "Inspector"),
    "inspector_2_headers": build_user_headers("insp-2", "Inspector"),
    "approver_headers": build_user_headers("appr-1", "ChargebackApprover"),
    "approver_2_headers": build_user_headers("appr-2", "ChargebackApprover"),
    # Entity-backed fallbacks — only for tests that never touch ownership.
    "branch_manager_headers": build_user_headers("test-branch-manager-1", "BranchManager"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}

# Stable operator ids, so segregation-of-duties comparisons are expressible.
FLEET_ADMIN_USER_ID = "admin-1"
INSPECTOR_USER_ID = "insp-1"
INSPECTOR_2_USER_ID = "insp-2"
APPROVER_USER_ID = "appr-1"
APPROVER_2_USER_ID = "appr-2"


def make_branch_manager_headers(branch_id: str) -> dict:
    """BranchManager acts as the Branch whose id is branch_id."""
    return build_user_headers(branch_id, "BranchManager")


def make_customer_headers(customer_id: str) -> dict:
    """Customer acts as the Customer whose id is customer_id."""
    return build_user_headers(customer_id, "Customer")


def make_inspector_headers(user_id: str) -> dict:
    """Inspector with an explicit opaque operator id (stamped as assessor_user_id)."""
    return build_user_headers(user_id, "Inspector")


def make_approver_headers(user_id: str) -> dict:
    """ChargebackApprover with an explicit opaque operator id."""
    return build_user_headers(user_id, "ChargebackApprover")


def make_fleet_admin_headers(user_id: str = FLEET_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "FleetAdmin")
