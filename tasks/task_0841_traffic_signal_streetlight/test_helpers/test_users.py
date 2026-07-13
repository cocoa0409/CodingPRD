"""Pre-built role headers for every role in the PRD (§2.1).

Four roles carry an opaque X-User-ID (Admin, Dispatcher, TrafficEngineer,
UtilityCoordinator). FieldTech is the one entity-backed role: its X-User-ID is
the id of the acting Crew, and completion is ownership-gated on it. For any
ownership-gated completion call, use make_fieldtech_headers(crew_id) with the
actual crew id — the shared constant below is a fallback for non-ownership tests
(e.g. RBAC-denial checks) only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "traffic_engineer_headers": build_user_headers("test-traffic-engineer-1", "TrafficEngineer"),
    "utility_coordinator_headers": build_user_headers("test-utility-coordinator-1", "UtilityCoordinator"),
    # entity_backed:Crew — shared constant never equals a real Crew.id, so it is
    # only valid for tests that do NOT exercise the ownership check.
    "fieldtech_headers": build_user_headers("test-fieldtech-1", "FieldTech"),
}


def make_fieldtech_headers(crew_id: str) -> dict:
    """For FieldTech (entity_backed:Crew). Pass the owning Crew.id as user_id
    whenever the completion call is ownership-gated."""
    return build_user_headers(crew_id, "FieldTech")
