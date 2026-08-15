"""Pre-built role headers for the six roles (PRD §2.1).

All six roles use opaque operator identities: the server never compares
X-User-ID against any resource's id, so shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "mechanic_headers": build_user_headers("test-mechanic-1", "Mechanic"),
    "station_agent_headers": build_user_headers("test-station-agent-1", "StationAgent"),
    "crew_manager_headers": build_user_headers("test-crew-manager-1", "CrewManager"),
    "catering_manager_headers": build_user_headers("test-catering-manager-1", "CateringManager"),
    "operations_manager_headers": build_user_headers("test-operations-manager-1", "OperationsManager"),
}

# Requests carrying no auth headers must be rejected with ERR_UNAUTHENTICATED (PRD §2.1).
ANONYMOUS_HEADERS: dict = {}
