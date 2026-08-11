"""Pre-built role headers for every role in the PRD (§2.1).

PermitHolder is entity-backed: X-User-ID must equal the acting PermitHolder's
id (PRD §2.1). Fixtures and tests MUST use make_permit_holder_headers() with
the real holder id for any ownership-gated call. The shared constant
TEST_USERS["permit_holder_headers"] is a fallback only for tests whose success
does not depend on the caller owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "community_admin_headers": build_user_headers("test-community-admin-1", "CommunityAdmin"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "enforcement_officer_headers": build_user_headers("test-enforcement-officer-1", "EnforcementOfficer"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "permit_holder_headers": build_user_headers("test-permit-holder-1", "PermitHolder"),
}


def make_permit_holder_headers(user_id: str) -> dict:
    """For PermitHolder (entity_backed:PermitHolder). Pass the actual
    PermitHolder.id as user_id whenever the call is ownership-gated
    (PRD §2.1: X-User-ID must equal the owning holder of the resource)."""
    return build_user_headers(user_id, "PermitHolder")
