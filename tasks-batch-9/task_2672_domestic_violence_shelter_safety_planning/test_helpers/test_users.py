"""Pre-built role headers for every role in the PRD.

The five operational roles bind `X-User-ID` to the acting StaffMember's `id`,
so ownership and separation-of-duty checks compare a resource's staff-member
reference to the header directly. Any call that is ownership-gated MUST be made
with the per-instance builder below, passing the real StaffMember id. The
AgencyAdmin identity is an opaque operator identifier that is never compared to
any entity's id, so the shared constant is the canonical form for that role.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AGENCY_ADMIN,
    ROLE_HOTLINE_ADVOCATE,
    ROLE_HOUSING_SPECIALIST,
    ROLE_LEGAL_ADVOCATE,
    ROLE_PRIVACY_OFFICER,
    ROLE_SHELTER_MANAGER,
)

# Shared constants. Safe for the opaque AgencyAdmin identity, and for calls that
# do not depend on the caller owning the subject resource (missing-header checks,
# unknown-id checks, role-authorisation checks).
TEST_USERS = {
    "hotline_advocate_headers": build_user_headers(
        "test-hotline-advocate-1", ROLE_HOTLINE_ADVOCATE
    ),
    "shelter_manager_headers": build_user_headers(
        "test-shelter-manager-1", ROLE_SHELTER_MANAGER
    ),
    "legal_advocate_headers": build_user_headers(
        "test-legal-advocate-1", ROLE_LEGAL_ADVOCATE
    ),
    "housing_specialist_headers": build_user_headers(
        "test-housing-specialist-1", ROLE_HOUSING_SPECIALIST
    ),
    "privacy_officer_headers": build_user_headers(
        "test-privacy-officer-1", ROLE_PRIVACY_OFFICER
    ),
    "agency_admin_headers": build_user_headers("test-agency-admin-1", ROLE_AGENCY_ADMIN),
}

ADMIN_HEADERS = TEST_USERS["agency_admin_headers"]


def make_hotline_advocate_headers(user_id: str) -> dict:
    """Headers for a HotlineAdvocate. Pass the acting StaffMember's id."""
    return build_user_headers(user_id, ROLE_HOTLINE_ADVOCATE)


def make_shelter_manager_headers(user_id: str) -> dict:
    """Headers for a ShelterManager. Pass the acting StaffMember's id."""
    return build_user_headers(user_id, ROLE_SHELTER_MANAGER)


def make_legal_advocate_headers(user_id: str) -> dict:
    """Headers for a LegalAdvocate. Pass the acting StaffMember's id."""
    return build_user_headers(user_id, ROLE_LEGAL_ADVOCATE)


def make_housing_specialist_headers(user_id: str) -> dict:
    """Headers for a HousingSpecialist. Pass the acting StaffMember's id."""
    return build_user_headers(user_id, ROLE_HOUSING_SPECIALIST)


def make_privacy_officer_headers(user_id: str) -> dict:
    """Headers for a PrivacyOfficer. Pass the acting StaffMember's id."""
    return build_user_headers(user_id, ROLE_PRIVACY_OFFICER)


def make_agency_admin_headers(user_id: str = "test-agency-admin-1") -> dict:
    """Headers for an AgencyAdmin. The identifier is opaque by design."""
    return build_user_headers(user_id, ROLE_AGENCY_ADMIN)
