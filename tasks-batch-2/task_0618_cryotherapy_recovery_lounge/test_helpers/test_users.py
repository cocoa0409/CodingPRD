"""Pre-built role headers for every role in the PRD.

PlatformAdmin and LocationManager carry an opaque X-User-ID not tied to any entity, so the
shared constants are the canonical form. Member and Technician are entity-backed: their
X-User-ID must equal the acting entity's id on ownership-gated calls, so use the per-instance
builders make_member_headers(member_id) / make_technician_headers(technician_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for the opaque roles; for Member/Technician these are only a
# fallback for tests that do NOT exercise ownership (e.g. 401/forbidden/not-found paths).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "manager_headers": build_user_headers("test-manager-1", "LocationManager"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
}


# Per-instance builders — required for the entity-backed roles.
def make_member_headers(member_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id whenever the
    call is ownership-gated (booking, subscription, waiver, pack on the member's own resources)."""
    return build_user_headers(member_id, "Member")


def make_technician_headers(technician_id: str) -> dict:
    """For the Technician role (entity_backed:Technician). Pass the actual Technician.id when
    completing or no-showing a session on the technician's own covering shift."""
    return build_user_headers(technician_id, "Technician")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "LocationManager")
