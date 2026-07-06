"""Pre-built role headers for every role in the PRD.

Role identities (PRD §2.1):
- Resident: `entity_backed:Resident`  — X-User-ID must equal a live Resident.id
- Moderator: `entity_backed:Resident` — X-User-ID must equal a live Resident.id
  whose is_moderator=true
- BusinessOwner: `entity_backed:Business` — X-User-ID must equal a live Business.id
- AgencyOfficer: opaque — X-User-ID recorded as agency_officer_id but never
  compared to any entity's id
- PlatformAdmin: opaque — X-User-ID recorded but never compared

For entity_backed roles, tests MUST call the per-instance builder with the
actual entity id whenever the endpoint is ownership-gated; a fallback to the
shared constant would present an X-User-ID that never equals any real entity's
id, causing every request to be rejected as ERR_UNAUTHENTICATED.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    PLATFORM_ADMIN_USER_ID,
    AGENCY_OFFICER_USER_ID,
    AGENCY_OFFICER_2_USER_ID,
)


# Shared constants — safe only for tests that don't exercise ownership. For
# opaque roles (PlatformAdmin, AgencyOfficer) the shared constant is canonical.
# For entity_backed roles the shared constants are placeholders used only when
# the test doesn't care about identity — e.g. asserting a 401 on an unknown id.
TEST_USERS = {
    "admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
    "officer_headers": build_user_headers(AGENCY_OFFICER_USER_ID, "AgencyOfficer"),
    "officer2_headers": build_user_headers(AGENCY_OFFICER_2_USER_ID, "AgencyOfficer"),
    # Fallbacks for entity_backed roles used ONLY in tests that don't exercise
    # ownership — the id "test-resident" will not match any real Resident.
    "resident_headers": build_user_headers("test-resident", "Resident"),
    "moderator_headers": build_user_headers("test-moderator", "Moderator"),
    "business_owner_headers": build_user_headers("test-business", "BusinessOwner"),
}


def make_resident_headers(resident_id: str) -> dict:
    """Headers for a Resident whose X-User-ID is that live Resident's id."""
    return build_user_headers(resident_id, "Resident")


def make_moderator_headers(resident_id: str) -> dict:
    """Headers for a Moderator — X-User-ID must be a live Resident.id whose
    is_moderator=true (PRD §2.1)."""
    return build_user_headers(resident_id, "Moderator")


def make_business_owner_headers(business_id: str) -> dict:
    """Headers for a BusinessOwner whose X-User-ID is that live Business's id."""
    return build_user_headers(business_id, "BusinessOwner")


def make_agency_officer_headers(officer_id: str = AGENCY_OFFICER_USER_ID) -> dict:
    """Headers for an opaque AgencyOfficer. The officer_id becomes
    agency_officer_id on published CivicNotices and acknowledged_by_officer_id
    on Incidents — retract and resolve compare that recorded id."""
    return build_user_headers(officer_id, "AgencyOfficer")


def make_admin_headers(admin_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    """Headers for opaque PlatformAdmin."""
    return build_user_headers(admin_id, "PlatformAdmin")
