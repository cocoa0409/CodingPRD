"""Acting identities for the Pentest Assurance API test suite.

Four of the five roles carry an opaque operator identifier that the server never
resolves to a persisted row, so those identities can be declared as constants.
The ``Tester`` role is different: ``X-User-ID`` must be the ``id`` of a real
tester record, so tester headers are always built from a live identifier with
:func:`make_tester_headers`.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PLATFORM_ADMIN,
    ROLE_PROGRAM_MANAGER,
    ROLE_REMEDIATION_OWNER,
    ROLE_TESTER,
)

# Opaque operator identifiers.
ADMIN_USER_ID = "admin-1"
ADMIN_ALT_USER_ID = "admin-2"
PM_USER_ID = "pm-1"
PM_ALT_USER_ID = "pm-2"
PM_DRAFTER_USER_ID = "u-1"
CO_USER_ID = "co-1"
CO_ALT_USER_ID = "co-2"
CO_INDEPENDENT_USER_ID = "co-9"
OWNER_USER_ID = "owner-1"
OWNER_ALT_USER_ID = "owner-2"

UNRECOGNISED_ROLE = "SecurityLead"


def admin_headers(user_id=ADMIN_USER_ID):
    """Headers for the programme registrar."""
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def program_manager_headers(user_id=PM_USER_ID):
    """Headers for the programme manager."""
    return build_user_headers(user_id, ROLE_PROGRAM_MANAGER)


def compliance_officer_headers(user_id=CO_USER_ID):
    """Headers for the independent assurance authority."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def remediation_owner_headers(user_id=OWNER_USER_ID):
    """Headers for the accountable owner of a fix."""
    return build_user_headers(user_id, ROLE_REMEDIATION_OWNER)


def make_tester_headers(tester_id):
    """Headers for a tester, whose ``X-User-ID`` is their own record id."""
    return build_user_headers(tester_id, ROLE_TESTER)


def headers_with_role(user_id, role):
    """Headers naming an arbitrary role, used for refusal ladders."""
    return build_user_headers(user_id, role)


def blank_user_id_headers(role=ROLE_PROGRAM_MANAGER):
    """Headers whose ``X-User-ID`` is present but blank."""
    headers = build_user_headers("", role)
    headers["X-User-ID"] = ""
    return headers


def whitespace_user_id_headers(role=ROLE_PROGRAM_MANAGER):
    """Headers whose ``X-User-ID`` contains only whitespace."""
    headers = build_user_headers("   ", role)
    headers["X-User-ID"] = "   "
    return headers


def headers_without_role(user_id=PM_USER_ID):
    """Headers that omit ``X-User-Role`` entirely."""
    headers = build_user_headers(user_id, ROLE_PROGRAM_MANAGER)
    headers.pop("X-User-Role", None)
    return headers


def headers_without_user_id(role=ROLE_PROGRAM_MANAGER):
    """Headers that omit ``X-User-ID`` entirely."""
    headers = build_user_headers(PM_USER_ID, role)
    headers.pop("X-User-ID", None)
    return headers
