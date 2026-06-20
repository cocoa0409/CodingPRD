"""Pre-built role headers for every role in the PRD (§2.1).

The PRD recognizes exactly three roles: FacilityManager, FacilityStaff, and
Owner. FacilityManager and FacilityStaff are opaque operator identities — their
X-User-ID is never compared to any entity. The Owner role is entity-backed:
when X-User-Role is Owner, X-User-ID must be the acting Owner's id, and
ownership checks compare a resource's owner_id to that id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the two opaque operator roles, and for any test
# whose success does not depend on the Owner owning the subject resource.
TEST_USERS = {
    "manager_headers": build_user_headers("test-manager-1", "FacilityManager"),
    "staff_headers": build_user_headers("test-staff-1", "FacilityStaff"),
    # Fallback only — for non-ownership Owner tests (e.g. 403/404 negative paths).
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
}


def make_owner_headers(user_id: str) -> dict:
    """For the entity-backed Owner role. Pass the actual Owner.id as user_id
    whenever the call is ownership-gated (creating/cancelling that owner's own
    reservation, paying their deposit, managing their pets/packages)."""
    return build_user_headers(user_id, "Owner")
