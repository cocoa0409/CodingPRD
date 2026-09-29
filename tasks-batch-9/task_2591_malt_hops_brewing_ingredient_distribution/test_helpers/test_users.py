"""Pre-built role headers for every role the PRD declares (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#
# Brewer identity is entity-backed: `X-User-ID` must be the acting Brewer's own
# `id`, so the shared constant below is usable only where ownership is NOT the
# thing under test (bad-payload 400s, missing-resource 404s, role-permission
# 403s). Every ownership-gated call must use make_brewer_headers(brewer["id"]).
#
# The other four roles carry an opaque operator identifier that is never
# compared against any entity's id, so the shared constants are canonical.
TEST_USERS = {
    "brewer_headers": build_user_headers("test-brewer-unbound", "Brewer"),
    "allocation_manager_headers": build_user_headers("am-user-1",
                                                     "AllocationManager"),
    "allocation_manager_2_headers": build_user_headers("am-user-2",
                                                       "AllocationManager"),
    "credit_manager_headers": build_user_headers("cm-user-1", "CreditManager"),
    "warehouse_operator_headers": build_user_headers("wh-user-1",
                                                    "WarehouseOperator"),
    "warehouse_operator_2_headers": build_user_headers("wh-user-2",
                                                       "WarehouseOperator"),
    "platform_admin_headers": build_user_headers("pa-user-1", "PlatformAdmin"),
    # A syntactically invalid role, for the ERR_INVALID_ROLE gate.
    "invalid_role_headers": build_user_headers("someone", "Maltster"),
}

ROLE_HEADER_KEYS = {
    "Brewer": "brewer_headers",
    "AllocationManager": "allocation_manager_headers",
    "CreditManager": "credit_manager_headers",
    "WarehouseOperator": "warehouse_operator_headers",
    "PlatformAdmin": "platform_admin_headers",
}


def make_brewer_headers(brewer_id: str) -> dict:
    """Headers for the Brewer role, whose X-User-ID is the Brewer entity's id.

    Mandatory whenever the call is ownership-scoped: contracts, orders, order
    lines, recipes, propagation jobs, substitution offers and payments.
    """
    return build_user_headers(brewer_id, "Brewer")


def make_allocation_manager_headers(user_id: str) -> dict:
    """Headers for a specific AllocationManager operator identifier.

    Needed by the resale segregation-of-duties gate, which compares the acting
    X-User-ID against the contract's recorded defaulted_by_user_id.
    """
    return build_user_headers(user_id, "AllocationManager")


def make_warehouse_operator_headers(user_id: str) -> dict:
    """Headers for a specific WarehouseOperator operator identifier.

    Needed by the malt-lot release segregation-of-duties gate, which compares
    the acting X-User-ID against the lot's recorded analyzed_by_user_id.
    """
    return build_user_headers(user_id, "WarehouseOperator")


def make_credit_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CreditManager")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def headers_for_role(role: str) -> dict:
    """Shared-constant headers for a role name, for role-permission tests."""
    return TEST_USERS[ROLE_HEADER_KEYS[role]]
