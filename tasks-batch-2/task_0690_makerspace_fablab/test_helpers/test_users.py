"""Pre-built role headers for every role in the PRD (§2.1).

Member and StaffInstructor are entity-backed roles: X-User-ID must equal the id
of a real Member record for ownership checks to pass. FacilityAdmin is an opaque
operator role whose X-User-ID is not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - facility_admin_headers: opaque role; the shared constant is the canonical form.
#   - member_headers / staff_headers: entity-backed; the shared constant is a
#     fallback for tests that do NOT exercise ownership (e.g. 403 role-denied on a
#     FacilityAdmin-exclusive endpoint, 401 missing-header). Ownership-gated calls
#     MUST use the per-instance builders below with the real entity id.
TEST_USERS = {
    "facility_admin_headers": build_user_headers("admin-operator-1", "FacilityAdmin"),
    "member_headers": build_user_headers("member-fallback-1", "Member"),
    "staff_headers": build_user_headers("staff-fallback-1", "StaffInstructor"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the acting Member.id as
    user_id whenever the call is ownership-gated (own reservations, lockers,
    purchases, enrollments, subscription)."""
    return build_user_headers(user_id, "Member")


def make_staff_headers(user_id: str) -> dict:
    """For the StaffInstructor role (entity_backed:Member). Pass the staff
    Member.id (the same id used as a workshop instructor_id). Staff also have
    read access across resources."""
    return build_user_headers(user_id, "StaffInstructor")


def make_facility_admin_headers(user_id: str = "admin-operator-1") -> dict:
    """For the FacilityAdmin opaque operator role."""
    return build_user_headers(user_id, "FacilityAdmin")
