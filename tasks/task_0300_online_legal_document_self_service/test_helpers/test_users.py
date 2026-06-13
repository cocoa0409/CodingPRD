"""Pre-built role headers for every role in the PRD.

The PRD ties X-User-ID to a real entity id for Customer (the acting Customer.id)
and Attorney (the acting Attorney.id), but treats PlatformAdmin's X-User-ID as an
opaque operator identifier not compared to any entity. Ownership-gated calls must
therefore use the per-instance builders with the real entity id; the shared
constants are only safe for non-ownership tests (bad payload, missing resource,
PlatformAdmin operations).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "attorney_headers": build_user_headers("test-attorney-1", "Attorney"),
    # opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (project/order/review/signature ownership)."""
    return build_user_headers(user_id, "Customer")


def make_attorney_headers(user_id: str) -> dict:
    """For Attorney (entity_backed:Attorney). Pass the actual Attorney.id as user_id
    whenever advancing a review (the attorney_id ownership check)."""
    return build_user_headers(user_id, "Attorney")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For PlatformAdmin (opaque). X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")
