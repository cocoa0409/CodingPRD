"""Pre-built role headers for every role in the PRD.

All three roles use an opaque identity model (PRD §2.1): X-User-ID is an opaque
operator identifier never compared to any entity id. There are no ownership checks,
so shared constants are the canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "counselor_headers": build_user_headers("test-counselor-1", "CrisisCounselor"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "CrisisDispatcher"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "ClinicalSupervisor"),
}
