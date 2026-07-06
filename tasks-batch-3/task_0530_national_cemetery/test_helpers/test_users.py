"""Pre-built role headers for every role in the PRD.

All five roles are opaque operator identities: the X-User-ID is never compared
against any resource id, so a single shared constant per role is correct for
every call (there are no ownership-gated, entity-backed roles).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "NCA_Admin"),
    "eligibility_officer_headers": build_user_headers("test-elig-1", "EligibilityOfficer"),
    "scheduling_clerk_headers": build_user_headers("test-sched-1", "SchedulingClerk"),
    "marker_clerk_headers": build_user_headers("test-marker-1", "MarkerClerk"),
    "honors_coordinator_headers": build_user_headers("test-honors-1", "HonorsCoordinator"),
}

# Headers with NO auth fields, for the unauthenticated (401) test.
NO_AUTH_HEADERS: dict = {}
