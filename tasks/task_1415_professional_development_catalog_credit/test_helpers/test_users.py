"""Pre-built role headers for every role in the PRD (§2.1).

Teacher / BuildingAdmin / Instructor are entity-backed: X-User-ID must be the id
of a real Employee of the matching kind, so ownership-gated calls MUST use the
per-instance builders with the actual employee id. The shared constants are only
safe for opaque roles or for tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — canonical shared form.
    "coordinator_headers": build_user_headers("coord-0", "PDCoordinator"),
    "officer_headers": build_user_headers("officer-0", "BusinessOfficer"),
    "auditor_headers": build_user_headers("aud-0", "Auditor"),
    # Entity-backed roles — fallback only for non-ownership tests.
    "teacher_headers": build_user_headers("test-teacher-0", "Teacher"),
    "building_admin_headers": build_user_headers("test-admin-0", "BuildingAdmin"),
    "instructor_headers": build_user_headers("test-instructor-0", "Instructor"),
}


def make_teacher_headers(employee_id: str) -> dict:
    """Teacher is entity-backed: pass the acting teacher Employee.id."""
    return build_user_headers(employee_id, "Teacher")


def make_building_admin_headers(employee_id: str) -> dict:
    """BuildingAdmin is entity-backed: pass the admin Employee.id (kind ADMIN)."""
    return build_user_headers(employee_id, "BuildingAdmin")


def make_instructor_headers(employee_id: str) -> dict:
    """Instructor is entity-backed: pass the Employee.id named as section instructor."""
    return build_user_headers(employee_id, "Instructor")


def make_coordinator_headers(user_id: str = "coord-0") -> dict:
    """PDCoordinator is opaque; pass a distinct id to exercise segregation checks."""
    return build_user_headers(user_id, "PDCoordinator")


def make_officer_headers(user_id: str = "officer-0") -> dict:
    """BusinessOfficer is opaque; pass a distinct id to exercise segregation checks."""
    return build_user_headers(user_id, "BusinessOfficer")


def make_auditor_headers(user_id: str = "aud-0") -> dict:
    """Auditor is an opaque, independent identity."""
    return build_user_headers(user_id, "Auditor")
