"""Pre-built role headers for every role the PRD declares.

PlanningAdmin, Allocator and AllocationManager are opaque identities, so the
shared constants below are the canonical form for them.  StoreOperator is the
receiving store itself and its ``X-User-ID`` is the Store id, so ownership-gated
StoreOperator calls MUST use :func:`make_store_operator_headers` with the real
Store id rather than the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

PLANNING_ADMIN_USER_ID = "u-plan-1"
ALLOCATOR_USER_ID = "u-alloc-1"
ALLOCATION_MANAGER_USER_ID = "u-mgr-1"
SECOND_ALLOCATOR_USER_ID = "u-alloc-2"
SECOND_MANAGER_USER_ID = "u-mgr-2"

TEST_USERS = {
    "planning_admin_headers": build_user_headers(PLANNING_ADMIN_USER_ID, "PlanningAdmin"),
    "allocator_headers": build_user_headers(ALLOCATOR_USER_ID, "Allocator"),
    "allocation_manager_headers": build_user_headers(
        ALLOCATION_MANAGER_USER_ID, "AllocationManager"
    ),
    "second_allocator_headers": build_user_headers(SECOND_ALLOCATOR_USER_ID, "Allocator"),
    "second_manager_headers": build_user_headers(
        SECOND_MANAGER_USER_ID, "AllocationManager"
    ),
    # Fallback only: valid role, but not any real Store id. Use it exclusively for
    # tests that do not depend on the caller owning the subject store.
    "store_operator_headers": build_user_headers("s-unknown-store", "StoreOperator"),
}


def make_planning_admin_headers(user_id: str = PLANNING_ADMIN_USER_ID) -> dict:
    """Headers for PlanningAdmin (opaque identity)."""
    return build_user_headers(user_id, "PlanningAdmin")


def make_allocator_headers(user_id: str = ALLOCATOR_USER_ID) -> dict:
    """Headers for Allocator (opaque identity)."""
    return build_user_headers(user_id, "Allocator")


def make_allocation_manager_headers(user_id: str = ALLOCATION_MANAGER_USER_ID) -> dict:
    """Headers for AllocationManager (opaque identity)."""
    return build_user_headers(user_id, "AllocationManager")


def make_store_operator_headers(store_id: str) -> dict:
    """Headers for StoreOperator. ``store_id`` must be the real Store id whose
    data the call touches, because the operator identity IS the store."""
    return build_user_headers(store_id, "StoreOperator")
