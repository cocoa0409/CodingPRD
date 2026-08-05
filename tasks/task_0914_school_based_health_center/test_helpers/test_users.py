"""Pre-built role headers for the seven roles the PRD declares (§2.1).

Three of the seven roles are entity-backed: a `Clinician`'s `X-User-ID` is the
id of the acting `Clinician` row, a `Guardian`'s is the id of the acting
`Guardian` row and a `Student`'s is the id of the acting `Student` row. For
those three, ownership-gated calls MUST use the per-instance builder below with
the real row id — never the shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the four opaque roles, and for entity-backed
# roles only in tests that never exercise ownership.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "SbhcAdmin"),
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "care_coordinator_headers": build_user_headers("test-coordinator-1", "CareCoordinator"),
    "billing_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
    # entity_backed roles: fallbacks for non-ownership tests only.
    "clinician_headers": build_user_headers("test-clinician-1", "Clinician"),
    "guardian_headers": build_user_headers("test-guardian-1", "Guardian"),
    "student_headers": build_user_headers("test-student-1", "Student"),
}

# Convenient aliases for the four opaque roles.
ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
CARE_COORDINATOR = TEST_USERS["care_coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


def make_clinician_headers(clinician_id: str) -> dict:
    """Headers for a `Clinician`. Pass the actual Clinician row id: the referral
    segregation-of-duties rule and every clinician-valued comparison read it."""
    return build_user_headers(clinician_id, "Clinician")


def make_guardian_headers(guardian_id: str) -> dict:
    """Headers for a `Guardian`. Pass the actual Guardian row id: notification
    acknowledgement and the preference switch compare against it."""
    return build_user_headers(guardian_id, "Guardian")


def make_student_headers(student_id: str) -> dict:
    """Headers for a `Student`. Pass the actual Student row id: self-consent
    ownership compares it to the student id in the path."""
    return build_user_headers(student_id, "Student")


def make_care_coordinator_headers(user_id: str) -> dict:
    """Headers for a `CareCoordinator` with a caller-chosen opaque identifier.
    Used when a test needs two distinct coordinators."""
    return build_user_headers(user_id, "CareCoordinator")


def make_headers(user_id: str, role: str) -> dict:
    """Escape hatch for tests that need an arbitrary id/role pair, including
    roles that are not among the seven declared ones."""
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS: dict = {}
"""A request carrying neither X-User-ID nor X-User-Role."""
