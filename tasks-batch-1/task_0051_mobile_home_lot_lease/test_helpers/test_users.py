"""Pre-built role headers for every role in the PRD.

ParkManager and HousingAuthority are opaque roles: X-User-ID is an arbitrary
operator identifier the server records but never compares to an entity id, so a
shared constant is always correct.

Resident is entity_backed: X-User-ID must equal the acting Resident entity's id,
because ownership checks compare a resource's resident FK to X-User-ID. Use
make_resident_headers(resident_id) with the real Resident.id on every
ownership-gated Resident call (accept/contest rent, cure eviction, pay, ballot).
The shared "resident_headers" constant is only safe for non-ownership tests
(e.g. a 403 RBAC check, or a 404 on a missing resource).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "manager_headers": build_user_headers("manager-op-1", "ParkManager"),
    "authority_headers": build_user_headers("authority-op-1", "HousingAuthority"),
    # Fallback Resident constant — ONLY for tests that do not exercise ownership.
    "resident_headers": build_user_headers("resident-fallback-1", "Resident"),
}


def make_manager_headers(user_id: str = "manager-op-1") -> dict:
    """ParkManager is opaque; user_id is arbitrary."""
    return build_user_headers(user_id, "ParkManager")


def make_authority_headers(user_id: str = "authority-op-1") -> dict:
    """HousingAuthority is opaque; user_id is arbitrary."""
    return build_user_headers(user_id, "HousingAuthority")


def make_resident_headers(resident_id: str) -> dict:
    """Resident is entity_backed:Resident. Pass the acting Resident.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(resident_id, "Resident")
