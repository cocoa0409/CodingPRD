"""Caller identities and the two headers every request carries (PRD §2.1).

``Guest`` and ``Host`` are entity-backed: the acting ``X-User-ID`` is compared
against the stored ``guest_id`` / ``host_id`` of the resource, so headers for
those roles can only be built once the backing row exists. The three staff roles
carry an opaque principal identifier that is never compared to stored data, so a
fixed constant is always acceptable for them.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_GUEST,
    ROLE_HOST,
    ROLE_PLATFORM_ADMIN,
    ROLE_TRUST_ADJUDICATOR,
)

ALL_ROLES = (
    ROLE_GUEST,
    ROLE_HOST,
    ROLE_TRUST_ADJUDICATOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PLATFORM_ADMIN,
)

ENTITY_BACKED_ROLES = {ROLE_GUEST: "Guest", ROLE_HOST: "Host"}

# Opaque principals. Two officers and two adjudicators exist because several
# decisions must be taken by a different person than the one who acted first.
COMPLIANCE_OFFICER_USER_ID = "co-1"
SECOND_COMPLIANCE_OFFICER_USER_ID = "co-2"
TRUST_ADJUDICATOR_USER_ID = "adj-1"
SECOND_TRUST_ADJUDICATOR_USER_ID = "adj-2"
PLATFORM_ADMIN_USER_ID = "admin-1"
READER_HOST_USER_ID = "reader-host"

OPAQUE_ROLE_USER_IDS = {
    ROLE_TRUST_ADJUDICATOR: TRUST_ADJUDICATOR_USER_ID,
    ROLE_COMPLIANCE_OFFICER: COMPLIANCE_OFFICER_USER_ID,
    ROLE_PLATFORM_ADMIN: PLATFORM_ADMIN_USER_ID,
}

# Placeholders for the entity-backed roles, used only where the request is
# refused before the identifier is ever compared with stored data — an
# unrecognised role, or a path identifier that resolves to nothing.
PLACEHOLDER_GUEST_USER_ID = "11111111-1111-4111-8111-111111111111"
PLACEHOLDER_HOST_USER_ID = "22222222-2222-4222-8222-222222222222"


def make_guest_headers(guest_id):
    """Headers for a Guest acting as the guest row with this id."""
    return build_user_headers(str(guest_id), ROLE_GUEST)


def make_host_headers(host_id):
    """Headers for a Host acting as the host row with this id."""
    return build_user_headers(str(host_id), ROLE_HOST)


def make_adjudicator_headers(user_id=TRUST_ADJUDICATOR_USER_ID):
    """Headers for a TrustAdjudicator, whose identifier is opaque."""
    return build_user_headers(str(user_id), ROLE_TRUST_ADJUDICATOR)


def make_compliance_officer_headers(user_id=COMPLIANCE_OFFICER_USER_ID):
    """Headers for a ComplianceOfficer, whose identifier is opaque."""
    return build_user_headers(str(user_id), ROLE_COMPLIANCE_OFFICER)


def make_platform_admin_headers(user_id=PLATFORM_ADMIN_USER_ID):
    """Headers for a PlatformAdmin, whose identifier is opaque."""
    return build_user_headers(str(user_id), ROLE_PLATFORM_ADMIN)


def make_headers(role, user_id):
    """Headers for an arbitrary role and identifier pair."""
    return build_user_headers(str(user_id), role)


def make_headers_without_user_id(role):
    """Headers that declare a role but omit X-User-ID entirely (PRD §2.1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_without_role(user_id):
    """Headers that carry an identifier but omit X-User-Role (PRD §2.1)."""
    return {"X-User-ID": str(user_id), "Content-Type": "application/json"}


def make_headers_with_empty_user_id(role):
    """Headers that supply X-User-ID as the empty string (PRD §2.1)."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


ADJUDICATOR = make_adjudicator_headers()
SECOND_ADJUDICATOR = make_adjudicator_headers(SECOND_TRUST_ADJUDICATOR_USER_ID)
COMPLIANCE_OFFICER = make_compliance_officer_headers()
SECOND_COMPLIANCE_OFFICER = make_compliance_officer_headers(
    SECOND_COMPLIANCE_OFFICER_USER_ID
)
PLATFORM_ADMIN = make_platform_admin_headers()
READER_HOST = make_host_headers(READER_HOST_USER_ID)

TEST_USERS = {
    ROLE_TRUST_ADJUDICATOR: ADJUDICATOR,
    ROLE_COMPLIANCE_OFFICER: COMPLIANCE_OFFICER,
    ROLE_PLATFORM_ADMIN: PLATFORM_ADMIN,
    # Entity-backed placeholders; only for pre-identity rejections.
    ROLE_GUEST: make_guest_headers(PLACEHOLDER_GUEST_USER_ID),
    ROLE_HOST: make_host_headers(PLACEHOLDER_HOST_USER_ID),
}
