"""Pre-built role headers for every role in the PRD (§2.1).

The Resident role is entity-backed: when X-User-Role is Resident, X-User-ID is
the id of the acting Resident record, and ownership checks compare the target
row's resident foreign key to X-User-ID. Any ownership-gated call MUST use
make_resident_headers(resident["id"]) with the real Resident.id. The shared
"resident_headers" constant is only a fallback for tests that never exercise
ownership (e.g. role-denied calls).

The other five roles use opaque operator identifiers; per-user builders exist
for tests that need specific X-User-ID values (evaluator stamping, CCC
segregation of duties, dismissal segregation of duties).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "dio_headers": build_user_headers("dio-1", "DesignatedInstitutionalOfficial"),
    "pd_headers": build_user_headers("pd-1", "ProgramDirector"),
    "pc_headers": build_user_headers("pc-1", "ProgramCoordinator"),
    "faculty_headers": build_user_headers("ev-1", "FacultyEvaluator"),
    "ccc_chair_headers": build_user_headers("chair-1", "CCCChair"),
    # Fallback for non-ownership contexts only; never a real Resident.id.
    "resident_headers": build_user_headers("resident-generic", "Resident"),
}


def make_dio_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DesignatedInstitutionalOfficial")


def make_pd_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramDirector")


def make_pc_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramCoordinator")


def make_faculty_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FacultyEvaluator")


def make_ccc_chair_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CCCChair")


def make_resident_headers(resident_id: str) -> dict:
    """Resident identity IS the Resident.id (PRD §2.1). Pass the real id whenever
    the call is ownership-gated (own duty logs, case logs, moonlighting)."""
    return build_user_headers(resident_id, "Resident")


def anonymous_headers() -> dict:
    """No user-context headers at all (PRD §2.8 stage 1 tests)."""
    return {}
