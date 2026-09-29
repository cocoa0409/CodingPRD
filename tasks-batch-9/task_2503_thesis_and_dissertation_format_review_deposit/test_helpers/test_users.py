"""Pre-built role headers for every role in the PRD (§2.1).

`Student` and `FacultyMember` are backed by persisted entities: X-User-ID must be
the acting entity's own `id`, so ownership-gated calls MUST use the per-instance
builders below. The other four roles are opaque operator identities, for which the
shared constants are the canonical form.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used across the suite. Two distinct identifiers exist
# for each role that participates in a segregation-of-duties pair (§2.8).
REGISTRAR_USER_ID = "reg-1"
ANALYST_ONE_USER_ID = "analyst-1"
ANALYST_TWO_USER_ID = "analyst-2"
DEAN_ONE_USER_ID = "dean-1"
DEAN_TWO_USER_ID = "dean-2"
INTEGRITY_OFFICER_ONE_USER_ID = "io-1"
INTEGRITY_OFFICER_TWO_USER_ID = "io-2"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants are canonical.
    "registrar_headers": build_user_headers(REGISTRAR_USER_ID, "Registrar"),
    "analyst_headers": build_user_headers(ANALYST_ONE_USER_ID, "GradSchoolAnalyst"),
    "analyst_two_headers": build_user_headers(ANALYST_TWO_USER_ID, "GradSchoolAnalyst"),
    "dean_headers": build_user_headers(DEAN_ONE_USER_ID, "GraduateDean"),
    "dean_two_headers": build_user_headers(DEAN_TWO_USER_ID, "GraduateDean"),
    "integrity_officer_headers": build_user_headers(
        INTEGRITY_OFFICER_ONE_USER_ID, "IntegrityOfficer"
    ),
    "integrity_officer_two_headers": build_user_headers(
        INTEGRITY_OFFICER_TWO_USER_ID, "IntegrityOfficer"
    ),
    # Entity-backed roles — fallback only for tests that never exercise ownership.
    "student_headers": build_user_headers("test-student-1", "Student"),
    "faculty_member_headers": build_user_headers("test-faculty-1", "FacultyMember"),
}


def make_student_headers(student_id: str) -> Dict[str, str]:
    """For `Student` (entity-backed). Pass the acting Student's own `id`."""
    return build_user_headers(student_id, "Student")


def make_faculty_member_headers(faculty_id: str) -> Dict[str, str]:
    """For `FacultyMember` (entity-backed). Pass the acting FacultyMember's own `id`."""
    return build_user_headers(faculty_id, "FacultyMember")


def make_registrar_headers(user_id: str = REGISTRAR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "Registrar")


def make_analyst_headers(user_id: str = ANALYST_ONE_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "GradSchoolAnalyst")


def make_dean_headers(user_id: str = DEAN_ONE_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "GraduateDean")


def make_integrity_officer_headers(
    user_id: str = INTEGRITY_OFFICER_ONE_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "IntegrityOfficer")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for role-denial tests that need an arbitrary role string."""
    return build_user_headers(user_id, role)
