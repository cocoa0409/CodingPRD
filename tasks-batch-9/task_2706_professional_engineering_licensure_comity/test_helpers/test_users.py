"""Caller identities and header builders for every role in the PRD.

Roles that are backed by a stored entity (Applicant, SupervisingEngineer and
Licensee are backed by an Engineer; FirmAdmin is backed by a FirmRegistration)
must present the identifier of the very row they act for, otherwise an
ownership check legitimately rejects the call. Use the ``make_*_headers``
builders for those roles and pass the real entity id. The board-side roles are
opaque, so their identifiers are free-form strings.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

TEST_USERS = {
    "applicant": {"user_id": "APPLICANT-1", "role": UserRole.APPLICANT.value},
    "supervising_engineer": {
        "user_id": "SUPERVISOR-1",
        "role": UserRole.SUPERVISING_ENGINEER.value,
    },
    "licensee": {"user_id": "LICENSEE-1", "role": UserRole.LICENSEE.value},
    "firm_admin": {"user_id": "FIRM-ADMIN-1", "role": UserRole.FIRM_ADMIN.value},
    "board_reviewer": {"user_id": "REV-1", "role": UserRole.BOARD_REVIEWER.value},
    "board_reviewer_2": {"user_id": "REV-2", "role": UserRole.BOARD_REVIEWER.value},
    "board_licensing_officer": {
        "user_id": "LIC-1",
        "role": UserRole.BOARD_LICENSING_OFFICER.value,
    },
    "board_licensing_officer_2": {
        "user_id": "LIC-2",
        "role": UserRole.BOARD_LICENSING_OFFICER.value,
    },
    "board_investigator": {"user_id": "INV-1", "role": UserRole.BOARD_INVESTIGATOR.value},
    "board_investigator_2": {
        "user_id": "INV-2",
        "role": UserRole.BOARD_INVESTIGATOR.value,
    },
    "board_secretary": {"user_id": "SEC-1", "role": UserRole.BOARD_SECRETARY.value},
    "board_secretary_2": {"user_id": "SEC-9", "role": UserRole.BOARD_SECRETARY.value},
    "testing_service": {"user_id": "TESTING-1", "role": UserRole.TESTING_SERVICE.value},
}


def _headers(key):
    user = TEST_USERS[key]
    return build_user_headers(user["user_id"], user["role"])


# ---------------------------------------------------------------------------
# Entity-backed roles: always pass the id of the row the caller acts for.
# ---------------------------------------------------------------------------
def make_applicant_headers(engineer_id):
    """Headers for the Applicant who *is* the engineer identified by the id."""
    return build_user_headers(str(engineer_id), UserRole.APPLICANT.value)


def make_supervising_engineer_headers(engineer_id):
    """Headers for the referee engineer identified by the id."""
    return build_user_headers(str(engineer_id), UserRole.SUPERVISING_ENGINEER.value)


def make_licensee_headers(engineer_id):
    """Headers for the licensed engineer identified by the id."""
    return build_user_headers(str(engineer_id), UserRole.LICENSEE.value)


def make_firm_admin_headers(firm_registration_id):
    """Headers for the administrator of the firm registration identified by the id."""
    return build_user_headers(str(firm_registration_id), UserRole.FIRM_ADMIN.value)


# ---------------------------------------------------------------------------
# Opaque board-side roles.
# ---------------------------------------------------------------------------
def make_board_reviewer_headers(user_id="REV-1"):
    return build_user_headers(user_id, UserRole.BOARD_REVIEWER.value)


def make_board_licensing_officer_headers(user_id="LIC-1"):
    return build_user_headers(user_id, UserRole.BOARD_LICENSING_OFFICER.value)


def make_board_investigator_headers(user_id="INV-1"):
    return build_user_headers(user_id, UserRole.BOARD_INVESTIGATOR.value)


def make_board_secretary_headers(user_id="SEC-1"):
    return build_user_headers(user_id, UserRole.BOARD_SECRETARY.value)


def make_testing_service_headers(user_id="TESTING-1"):
    return build_user_headers(user_id, UserRole.TESTING_SERVICE.value)


BOARD_REVIEWER_HEADERS = _headers("board_reviewer")
BOARD_REVIEWER_2_HEADERS = _headers("board_reviewer_2")
BOARD_LICENSING_OFFICER_HEADERS = _headers("board_licensing_officer")
BOARD_LICENSING_OFFICER_2_HEADERS = _headers("board_licensing_officer_2")
BOARD_INVESTIGATOR_HEADERS = _headers("board_investigator")
BOARD_INVESTIGATOR_2_HEADERS = _headers("board_investigator_2")
BOARD_SECRETARY_HEADERS = _headers("board_secretary")
TESTING_SERVICE_HEADERS = _headers("testing_service")
