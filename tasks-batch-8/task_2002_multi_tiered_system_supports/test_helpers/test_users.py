"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# interventionist ownership. PRD §2.1: for InterventionistRole, X-User-ID is the
# id of the acting Interventionist and ownership checks compare resource
# foreign keys to it; for every other role the identifier is opaque.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "district_coordinator_headers": build_user_headers("test-coordinator-1", "DistrictCoordinator"),
    "school_registrar_headers": build_user_headers("test-registrar-1", "SchoolRegistrar"),
    "teacher_headers": build_user_headers("test-teacher-1", "Teacher"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "interventionist_role_headers": build_user_headers("test-interventionist-1", "InterventionistRole"),
    "team_lead_headers": build_user_headers("test-team-lead-1", "TeamLead"),
    "sped_director_headers": build_user_headers("test-sped-director-1", "SpEdDirector"),
}


def make_interventionist_role_headers(user_id: str) -> dict:
    """For InterventionistRole (identity backed by the Interventionist entity).
    Pass the actual Interventionist.id as user_id whenever the call is
    ownership-gated (probe/session recording against that interventionist's plans)."""
    return build_user_headers(user_id, "InterventionistRole")
