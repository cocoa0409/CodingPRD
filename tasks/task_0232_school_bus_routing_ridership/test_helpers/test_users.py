"""Pre-built role headers for every role in the PRD (§2.1).

TransportAdmin is an opaque operator id (never compared to an entity id), so the
shared constant is the canonical form.

Driver is entity_backed: ownership checks compare the trip's driver foreign key to
X-User-ID, so driver calls MUST present the actual Driver.id via make_driver_headers().

Parent is entity_backed but its id is an opaque guardian id minted outside this API
and supplied as Student.parent_id. Parent calls present that same guardian string as
X-User-ID via make_parent_headers(). The default "par-1"/"par-2" guardians match the
parent_id values used in fixtures.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that do not exercise ownership.
TEST_USERS = {
    # opaque role: shared constant is canonical.
    "admin_headers": build_user_headers("test-admin-1", "TransportAdmin"),
    # entity_backed roles: shared-constant fallbacks for non-ownership tests only.
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "parent_headers": build_user_headers("par-1", "Parent"),
    "parent_2_headers": build_user_headers("par-2", "Parent"),
}


def make_admin_headers() -> dict:
    """TransportAdmin (opaque). X-User-ID is never compared to an entity id."""
    return build_user_headers("test-admin-1", "TransportAdmin")


def make_driver_headers(driver_id: str) -> dict:
    """For Driver (entity_backed:Driver). Pass the actual Driver.id as X-User-ID
    whenever the call is ownership-gated (any /bus-trips/{id} driver action)."""
    return build_user_headers(driver_id, "Driver")


def make_parent_headers(parent_id: str) -> dict:
    """For Parent (entity_backed:Parent). Pass the opaque guardian id used as the
    student's parent_id as X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(parent_id, "Parent")
