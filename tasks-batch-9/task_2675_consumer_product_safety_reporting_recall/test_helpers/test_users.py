"""Acting principals for every role, including alternates for the duty gates."""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Six of the seven roles carry an opaque operator identifier that is not tied to
# any persisted entity, so these are stable literals.
ADMIN_USER_ID = "admin-1"
ADMIN_ALT_USER_ID = "admin-2"
INTAKE_USER_ID = "intake-1"
INTAKE_ALT_USER_ID = "intake-2"
OFFICER_USER_ID = "co-1"
OFFICER_ALT_USER_ID = "co-2"
DIRECTOR_USER_ID = "dir-1"
DIRECTOR_ALT_USER_ID = "dir-2"
AUDITOR_USER_ID = "aud-1"
AUDITOR_ALT_USER_ID = "aud-2"
COUNSEL_USER_ID = "pc-1"
COUNSEL_ALT_USER_ID = "pc-2"

ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, Role.PROGRAM_ADMIN.value)
ADMIN_ALT_HEADERS = build_user_headers(ADMIN_ALT_USER_ID, Role.PROGRAM_ADMIN.value)
INTAKE_HEADERS = build_user_headers(INTAKE_USER_ID, Role.INTAKE_SPECIALIST.value)
INTAKE_ALT_HEADERS = build_user_headers(
    INTAKE_ALT_USER_ID, Role.INTAKE_SPECIALIST.value
)
OFFICER_HEADERS = build_user_headers(OFFICER_USER_ID, Role.COMPLIANCE_OFFICER.value)
OFFICER_ALT_HEADERS = build_user_headers(
    OFFICER_ALT_USER_ID, Role.COMPLIANCE_OFFICER.value
)
DIRECTOR_HEADERS = build_user_headers(DIRECTOR_USER_ID, Role.SAFETY_DIRECTOR.value)
DIRECTOR_ALT_HEADERS = build_user_headers(
    DIRECTOR_ALT_USER_ID, Role.SAFETY_DIRECTOR.value
)
AUDITOR_HEADERS = build_user_headers(AUDITOR_USER_ID, Role.FIELD_AUDITOR.value)
AUDITOR_ALT_HEADERS = build_user_headers(AUDITOR_ALT_USER_ID, Role.FIELD_AUDITOR.value)
COUNSEL_HEADERS = build_user_headers(COUNSEL_USER_ID, Role.PENALTY_COUNSEL.value)
COUNSEL_ALT_HEADERS = build_user_headers(
    COUNSEL_ALT_USER_ID, Role.PENALTY_COUNSEL.value
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    Role.PROGRAM_ADMIN.value: ADMIN_HEADERS,
    Role.INTAKE_SPECIALIST.value: INTAKE_HEADERS,
    Role.COMPLIANCE_OFFICER.value: OFFICER_HEADERS,
    Role.SAFETY_DIRECTOR.value: DIRECTOR_HEADERS,
    Role.FIELD_AUDITOR.value: AUDITOR_HEADERS,
    Role.PENALTY_COUNSEL.value: COUNSEL_HEADERS,
}

ALT_TEST_USERS: Dict[str, Dict[str, str]] = {
    Role.PROGRAM_ADMIN.value: ADMIN_ALT_HEADERS,
    Role.INTAKE_SPECIALIST.value: INTAKE_ALT_HEADERS,
    Role.COMPLIANCE_OFFICER.value: OFFICER_ALT_HEADERS,
    Role.SAFETY_DIRECTOR.value: DIRECTOR_ALT_HEADERS,
    Role.FIELD_AUDITOR.value: AUDITOR_ALT_HEADERS,
    Role.PENALTY_COUNSEL.value: COUNSEL_ALT_HEADERS,
}


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary principal and role pairing."""
    return build_user_headers(user_id, role)


def make_retailer_rep_headers(retailer_id: str) -> Dict[str, str]:
    """Headers for the representative of one retailer.

    RetailerRep is the entity-backed role: X-User-ID is the id of the acting
    Retailer.
    """
    return build_user_headers(retailer_id, Role.RETAILER_REP.value)


def headers_for(role: str) -> Dict[str, str]:
    """The canonical principal acting in one of the six opaque roles."""
    return TEST_USERS[role]


def alt_headers_for(role: str) -> Dict[str, str]:
    """A second, distinct principal acting in one of the six opaque roles."""
    return ALT_TEST_USERS[role]
