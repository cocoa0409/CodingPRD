"""Pre-built role headers for every role in the PRD.

All four roles are opaque operator identities: X-User-ID is never compared to any
persisted entity's id for ownership (PRD §2.1). Shared constants are therefore the
canonical form for every role — there are no entity_backed roles in this domain.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "account_manager_headers": build_user_headers("test-am-1", "AccountManager"),
    "media_specialist_headers": build_user_headers("test-ms-1", "MediaSpecialist"),
    "scheduling_coordinator_headers": build_user_headers("test-sc-1", "SchedulingCoordinator"),
    "platform_admin_headers": build_user_headers("test-pa-1", "PlatformAdmin"),
}
