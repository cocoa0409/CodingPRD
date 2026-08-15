"""Pre-built role headers for every role in the PRD (§2.1).

The Paraprofessional role is entity-backed: X-User-ID must be the acting
paraprofessional's own `id` whenever the call is ownership-gated (own
timesheets, own backfill offers, own evaluations, own absence reports).
Use make_para_headers(para["id"]) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "DistrictStaffingAdmin"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "SpecialEdCoordinator"),
    "building_admin_headers": build_user_headers("test-bldg-admin-1", "BuildingAdministrator"),
    "teacher_headers": build_user_headers("teacher-1", "Teacher"),
    "any_headers": build_user_headers("test-reader-1", "Any"),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "para_headers": build_user_headers("test-para-1", "Paraprofessional"),
}


def make_para_headers(para_id: str) -> dict:
    """For Paraprofessional (entity-backed). Pass the actual Paraprofessional.id
    whenever the call is ownership-gated (timesheets, backfill answers,
    evaluation acknowledge/dispute, own absence reports)."""
    return build_user_headers(para_id, "Paraprofessional")


def make_teacher_headers(user_id: str) -> dict:
    """For Teacher when a specific operator id must be recorded (evaluation author)."""
    return build_user_headers(user_id, "Teacher")


def make_building_admin_headers(user_id: str) -> dict:
    """For BuildingAdministrator when a specific operator id must be recorded
    (evaluation countersigner / resolver)."""
    return build_user_headers(user_id, "BuildingAdministrator")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DistrictStaffingAdmin")


def make_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SpecialEdCoordinator")


def make_any_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Any")
