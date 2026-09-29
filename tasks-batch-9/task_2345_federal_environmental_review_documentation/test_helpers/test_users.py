"""Pre-built role headers and per-role header builders (PRD 2.1).

Every request carries ``X-User-ID`` and ``X-User-Role``. For seven of the eight
roles ``X-User-ID`` is an opaque operator identifier that is never compared to
any entity's ``id``. For ``AgencyLiaison`` it is the ``id`` of the acting
``Agency``, so a liaison's headers can only be built once the agency exists —
use :func:`make_agency_liaison_headers` with that agency's ``id``.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------
# Opaque operator identifiers
# --------------------------------------------------------------------------

POLICY_ADMIN_USER_ID = "policy-admin-1"
NEPA_COORDINATOR_USER_ID = "coord-1"
RESOURCE_SPECIALIST_USER_ID = "specialist-4"
REVIEWING_OFFICIAL_USER_ID = "review-official-2"
DECIDING_OFFICIAL_USER_ID = "official-9"
OBJECTION_REVIEWING_OFFICER_USER_ID = "review-officer-3"
PUBLIC_COMMENTER_USER_ID = "public-commenter-7"

#: Placeholder identity for the entity-backed role; real calls must thread the
#: acting agency's id through make_agency_liaison_headers().
AGENCY_LIAISON_PLACEHOLDER_ID = "agency-liaison-placeholder"


# --------------------------------------------------------------------------
# Per-role header builders
# --------------------------------------------------------------------------

def make_policy_admin_headers(user_id: str = POLICY_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.POLICY_ADMIN.value)


def make_nepa_coordinator_headers(user_id: str = NEPA_COORDINATOR_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.NEPA_COORDINATOR.value)


def make_resource_specialist_headers(user_id: str = RESOURCE_SPECIALIST_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.RESOURCE_SPECIALIST.value)


def make_reviewing_official_headers(user_id: str = REVIEWING_OFFICIAL_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.REVIEWING_OFFICIAL.value)


def make_deciding_official_headers(user_id: str = DECIDING_OFFICIAL_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.DECIDING_OFFICIAL.value)


def make_objection_reviewing_officer_headers(
    user_id: str = OBJECTION_REVIEWING_OFFICER_USER_ID,
) -> dict:
    return build_user_headers(user_id, UserRole.OBJECTION_REVIEWING_OFFICER.value)


def make_public_commenter_headers(user_id: str = PUBLIC_COMMENTER_USER_ID) -> dict:
    return build_user_headers(user_id, UserRole.PUBLIC_COMMENTER.value)


def make_agency_liaison_headers(agency_id: str) -> dict:
    """Headers for an ``AgencyLiaison`` acting for the agency with ``agency_id``.

    ``X-User-ID`` must equal the agency's ``id``; ownership checks compare a
    consultation's ``agency_id`` against it.
    """
    return build_user_headers(agency_id, UserRole.AGENCY_LIAISON.value)


# --------------------------------------------------------------------------
# Shared header dictionaries
# --------------------------------------------------------------------------

TEST_USERS = {
    "policy_admin": make_policy_admin_headers(),
    "nepa_coordinator": make_nepa_coordinator_headers(),
    "resource_specialist": make_resource_specialist_headers(),
    "reviewing_official": make_reviewing_official_headers(),
    "deciding_official": make_deciding_official_headers(),
    "objection_reviewing_officer": make_objection_reviewing_officer_headers(),
    "public_commenter": make_public_commenter_headers(),
    "agency_liaison": make_agency_liaison_headers(AGENCY_LIAISON_PLACEHOLDER_ID),
}

POLICY_ADMIN_HEADERS = TEST_USERS["policy_admin"]
NEPA_COORDINATOR_HEADERS = TEST_USERS["nepa_coordinator"]
RESOURCE_SPECIALIST_HEADERS = TEST_USERS["resource_specialist"]
REVIEWING_OFFICIAL_HEADERS = TEST_USERS["reviewing_official"]
DECIDING_OFFICIAL_HEADERS = TEST_USERS["deciding_official"]
OBJECTION_REVIEWING_OFFICER_HEADERS = TEST_USERS["objection_reviewing_officer"]
PUBLIC_COMMENTER_HEADERS = TEST_USERS["public_commenter"]

#: A request carrying neither header at all (PRD 2.1).
NO_AUTH_HEADERS: dict = {"Content-Type": "application/json"}
