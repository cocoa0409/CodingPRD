"""Pre-built role headers for every role in the PRD.

Resident is entity-backed: the household `id` returned by the anonymous
registration IS the resident's X-User-ID. Any ownership-gated call MUST use
make_resident_headers(household["id"]) with the real household id. The shared
TEST_USERS entries are safe for opaque roles and for tests that do not
exercise ownership (bad payloads, missing resources, role-denial checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "anonymous_headers": build_user_headers("anon_0", "Anonymous"),
    # Fallback only — never valid for ownership-gated Resident calls.
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
    "driver_headers": build_user_headers("drv_1", "Driver"),
    "inspector_headers": build_user_headers("insp_1", "FieldInspector"),
    "supervisor_headers": build_user_headers("sup_1", "RouteSupervisor"),
    "clerk_headers": build_user_headers("clerk_1", "BillingClerk"),
    "admin_headers": build_user_headers("admin_1", "ProgramAdmin"),
    "coordinator_headers": build_user_headers("out_1", "OutreachCoordinator"),
}


def make_resident_headers(household_id: str) -> dict:
    """Resident identity is the Household id; required for ownership-gated calls."""
    return build_user_headers(household_id, "Resident")


def make_driver_headers(user_id: str = "drv_1") -> dict:
    return build_user_headers(user_id, "Driver")


def make_inspector_headers(user_id: str = "insp_1") -> dict:
    return build_user_headers(user_id, "FieldInspector")


def make_supervisor_headers(user_id: str = "sup_1") -> dict:
    return build_user_headers(user_id, "RouteSupervisor")


def make_clerk_headers(user_id: str = "clerk_1") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_admin_headers(user_id: str = "admin_1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_coordinator_headers(user_id: str = "out_1") -> dict:
    return build_user_headers(user_id, "OutreachCoordinator")


def make_anonymous_headers(user_id: str = "anon_0") -> dict:
    return build_user_headers(user_id, "Anonymous")
