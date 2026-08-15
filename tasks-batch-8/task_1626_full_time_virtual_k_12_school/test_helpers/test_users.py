"""Pre-built role headers for every role in the PRD.

All six roles use opaque operator identifiers: the PRD states that the
`X-User-ID` value is not tied to any persisted entity and that authorization
is purely role-based with no per-resource ownership checks. The shared
constants below are therefore the canonical form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "enrollment_officer_headers": build_user_headers("test-enrollment-officer-1", "EnrollmentOfficer"),
    "finance_officer_headers": build_user_headers("test-finance-officer-1", "FinanceOfficer"),
    "academic_director_headers": build_user_headers("test-academic-director-1", "AcademicDirector"),
    "proctor_coordinator_headers": build_user_headers("test-proctor-coordinator-1", "ProctorCoordinator"),
    "special_ed_coordinator_headers": build_user_headers("test-special-ed-coordinator-1", "SpecialEdCoordinator"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_enrollment_officer_headers(user_id: str = "test-enrollment-officer-1") -> dict:
    return build_user_headers(user_id, "EnrollmentOfficer")


def make_finance_officer_headers(user_id: str = "test-finance-officer-1") -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_academic_director_headers(user_id: str = "test-academic-director-1") -> dict:
    return build_user_headers(user_id, "AcademicDirector")


def make_proctor_coordinator_headers(user_id: str = "test-proctor-coordinator-1") -> dict:
    return build_user_headers(user_id, "ProctorCoordinator")


def make_special_ed_coordinator_headers(user_id: str = "test-special-ed-coordinator-1") -> dict:
    return build_user_headers(user_id, "SpecialEdCoordinator")
