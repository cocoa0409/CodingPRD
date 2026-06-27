"""Pre-built role headers for every role in the PRD.

ShopAdmin is opaque (X-User-ID is an operator id never tied to an entity), so a
shared constant is the canonical form. Instructor and Diver are entity_backed
(X-User-ID is the entity's id and ownership checks compare against it), so each
gets a per-instance builder; the shared constant is a fallback for non-ownership
tests only.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque role: shared constant is canonical.
    "shop_admin_headers": build_user_headers("shop-admin-1", "ShopAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests.
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "diver_headers": build_user_headers("test-diver-1", "Diver"),
}


def make_shop_admin_headers(user_id: str = "shop-admin-1") -> dict:
    """ShopAdmin is opaque; any operator id works and is never ownership-checked."""
    return build_user_headers(user_id, "ShopAdmin")


def make_instructor_headers(user_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the actual Instructor.id
    as user_id whenever the call is ownership-gated (complete/attend)."""
    return build_user_headers(user_id, "Instructor")


def make_diver_headers(user_id: str) -> dict:
    """For Diver (entity_backed:Diver). Pass the actual Diver.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Diver")


def make_unknown_role_headers(user_id: str = "ghost-1", role: str = "Ghost") -> dict:
    """Headers carrying an unrecognized role, for ERR_UNAUTHENTICATED tests."""
    return build_user_headers(user_id, role)
