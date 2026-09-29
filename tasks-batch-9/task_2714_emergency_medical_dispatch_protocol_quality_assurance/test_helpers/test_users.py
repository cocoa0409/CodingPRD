"""Role header builders.

The PRD requires two headers on every request: X-User-ID and X-User-Role.
Five roles carry an opaque identifier; the Dispatcher role's X-User-ID must be
the id of the dispatcher row that the caller acts as, so its headers are built
per dispatcher id.
"""

from prd_bench_local_runner.testing import build_user_headers

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_QA_SUPERVISOR = "QaSupervisor"
ROLE_QA_REVIEWER = "QaReviewer"
ROLE_MEDICAL_DIRECTOR = "MedicalDirector"
ROLE_ACCREDITATION_OFFICER = "AccreditationOfficer"
ROLE_DISPATCHER = "Dispatcher"

ALL_ROLES = [
    ROLE_PROGRAM_ADMIN,
    ROLE_QA_SUPERVISOR,
    ROLE_QA_REVIEWER,
    ROLE_MEDICAL_DIRECTOR,
    ROLE_ACCREDITATION_OFFICER,
    ROLE_DISPATCHER,
]

ADMIN_USER_ID = "admin-1"
SUPERVISOR_USER_ID = "sup-1"
SUPERVISOR_2_USER_ID = "sup-2"
REVIEWER_USER_ID = "rev-1"
REVIEWER_2_USER_ID = "rev-2"
DIRECTOR_USER_ID = "dir-1"
OFFICER_USER_ID = "acc-1"

ADMIN = build_user_headers(ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)
SUPERVISOR = build_user_headers(SUPERVISOR_USER_ID, ROLE_QA_SUPERVISOR)
SUPERVISOR_2 = build_user_headers(SUPERVISOR_2_USER_ID, ROLE_QA_SUPERVISOR)
REVIEWER = build_user_headers(REVIEWER_USER_ID, ROLE_QA_REVIEWER)
REVIEWER_2 = build_user_headers(REVIEWER_2_USER_ID, ROLE_QA_REVIEWER)
DIRECTOR = build_user_headers(DIRECTOR_USER_ID, ROLE_MEDICAL_DIRECTOR)
OFFICER = build_user_headers(OFFICER_USER_ID, ROLE_ACCREDITATION_OFFICER)

# Role -> a ready-made header dict, for role-matrix tests. The Dispatcher role
# is deliberately absent because its X-User-ID is data-dependent.
HEADERS_BY_ROLE = {
    ROLE_PROGRAM_ADMIN: ADMIN,
    ROLE_QA_SUPERVISOR: SUPERVISOR,
    ROLE_QA_REVIEWER: REVIEWER,
    ROLE_MEDICAL_DIRECTOR: DIRECTOR,
    ROLE_ACCREDITATION_OFFICER: OFFICER,
}


def make_dispatcher_headers(dispatcher_id: str) -> dict:
    """Headers for the Dispatcher role, whose X-User-ID is the dispatcher row id."""
    return build_user_headers(dispatcher_id, ROLE_DISPATCHER)


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary user id / role pair, for identity-sensitive assertions."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = ADMIN_USER_ID) -> dict:
    """A request that omits X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_PROGRAM_ADMIN) -> dict:
    """A request that omits X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = ADMIN_USER_ID) -> dict:
    """A request whose X-User-Role is not one of the six declared roles."""
    return build_user_headers(user_id, "ClinicalAuditor")
