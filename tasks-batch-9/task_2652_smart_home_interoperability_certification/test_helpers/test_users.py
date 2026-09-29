"""Request identities.

Two of the seven roles are backed by persisted rows: a ``Member`` acts as the
``id`` of its own member row and a ``TestLaboratory`` acts as the ``id`` of its
own laboratory row, so their headers must always be built from the real row
identifier returned by the create call. The other five roles carry opaque
operator identifiers that the server never compares against an entity id, which
is why they can be fixed constants here.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CONFORMANCE_REVIEWER,
    ROLE_MEMBER,
    ROLE_PROGRAM_ADMIN,
    ROLE_PUBLIC_VIEWER,
    ROLE_SECURITY_REVIEWER,
    ROLE_TEST_LABORATORY,
)

# --- Opaque operator identifiers -------------------------------------------

PROGRAM_ADMIN_USER_ID = "admin-1"
CONFORMANCE_REVIEWER_1 = "CONF1"
CONFORMANCE_REVIEWER_2 = "CONF2"
SECURITY_REVIEWER_1 = "SEC1"
SECURITY_REVIEWER_2 = "SEC2"
COMPLIANCE_OFFICER_1 = "CO1"
COMPLIANCE_OFFICER_2 = "CO2"
PUBLIC_VIEWER_USER_ID = "viewer-1"

ADMIN_HEADERS = build_user_headers(PROGRAM_ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)
CONFORMANCE_HEADERS = build_user_headers(
    CONFORMANCE_REVIEWER_1, ROLE_CONFORMANCE_REVIEWER
)
CONFORMANCE_HEADERS_2 = build_user_headers(
    CONFORMANCE_REVIEWER_2, ROLE_CONFORMANCE_REVIEWER
)
SECURITY_HEADERS = build_user_headers(SECURITY_REVIEWER_1, ROLE_SECURITY_REVIEWER)
SECURITY_HEADERS_2 = build_user_headers(SECURITY_REVIEWER_2, ROLE_SECURITY_REVIEWER)
COMPLIANCE_HEADERS = build_user_headers(COMPLIANCE_OFFICER_1, ROLE_COMPLIANCE_OFFICER)
COMPLIANCE_HEADERS_2 = build_user_headers(COMPLIANCE_OFFICER_2, ROLE_COMPLIANCE_OFFICER)
PUBLIC_HEADERS = build_user_headers(PUBLIC_VIEWER_USER_ID, ROLE_PUBLIC_VIEWER)


# --- Entity-backed identities ----------------------------------------------


def make_member_headers(member_id):
    """Headers for the member whose own row id is ``member_id``."""
    return build_user_headers(member_id, ROLE_MEMBER)


def make_laboratory_headers(laboratory_id):
    """Headers for the laboratory whose own row id is ``laboratory_id``."""
    return build_user_headers(laboratory_id, ROLE_TEST_LABORATORY)


# --- Arbitrary role/identity pairs -----------------------------------------


def make_headers(role, user_id):
    """Headers for an arbitrary role and identifier pair."""
    return build_user_headers(user_id, role)


def make_conformance_headers(user_id):
    return build_user_headers(user_id, ROLE_CONFORMANCE_REVIEWER)


def make_security_headers(user_id):
    return build_user_headers(user_id, ROLE_SECURITY_REVIEWER)


def make_compliance_headers(user_id):
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_admin_headers(user_id):
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


# --- Deliberately incomplete identities ------------------------------------


def headers_without_role(user_id=PROGRAM_ADMIN_USER_ID):
    """Only ``X-User-ID``; the role header is absent."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role=ROLE_PROGRAM_ADMIN):
    """Only ``X-User-Role``; the identity header is absent."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_no_identity():
    """Neither identity header is present."""
    return {"Content-Type": "application/json"}
