"""Pre-built role headers for every role named in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   ProgramManager / ScopingSpecialist / QualityReviewer carry an opaque operator
#   identifier that is never compared with any entity id, so the constants below
#   are the canonical form for those roles.
#   Volunteer and PartnerContact are identity-backed: their X-User-ID must be the
#   acting Volunteer.id / PartnerOrg.id. The shared constants for those two roles
#   are only safe for tests that never reach an ownership check (missing-resource
#   or bad-payload cases).
TEST_USERS = {
    "program_manager_headers": build_user_headers("pm-1", "ProgramManager"),
    "program_manager_2_headers": build_user_headers("pm-2", "ProgramManager"),
    "scoping_specialist_headers": build_user_headers("spec-1", "ScopingSpecialist"),
    "scoping_specialist_2_headers": build_user_headers("spec-2", "ScopingSpecialist"),
    "quality_reviewer_headers": build_user_headers("qr-1", "QualityReviewer"),
    "quality_reviewer_2_headers": build_user_headers("qr-2", "QualityReviewer"),
    "volunteer_headers": build_user_headers(
        "00000000-0000-4000-8000-0000000000v1", "Volunteer"
    ),
    "partner_contact_headers": build_user_headers(
        "00000000-0000-4000-8000-0000000000p1", "PartnerContact"
    ),
}

PM_USER_ID = "pm-1"
PM2_USER_ID = "pm-2"
SPEC_USER_ID = "spec-1"
SPEC2_USER_ID = "spec-2"
QR_USER_ID = "qr-1"
QR2_USER_ID = "qr-2"


def make_program_manager_headers(user_id: str = PM_USER_ID) -> dict:
    """ProgramManager is an opaque operator identity."""
    return build_user_headers(user_id, "ProgramManager")


def make_scoping_specialist_headers(user_id: str = SPEC_USER_ID) -> dict:
    """ScopingSpecialist is an opaque operator identity; the value lands on
    a drafted revision's authored_by_user_id."""
    return build_user_headers(user_id, "ScopingSpecialist")


def make_quality_reviewer_headers(user_id: str = QR_USER_ID) -> dict:
    """QualityReviewer is an opaque operator identity; the value lands on a
    review round's reviewer_user_id."""
    return build_user_headers(user_id, "QualityReviewer")


def make_volunteer_headers(user_id: str) -> dict:
    """For the Volunteer role. Pass the acting Volunteer's own id."""
    return build_user_headers(user_id, "Volunteer")


def make_partner_contact_headers(user_id: str) -> dict:
    """For the PartnerContact role. Pass the acting PartnerOrg's own id."""
    return build_user_headers(user_id, "PartnerContact")


def headers_for_role(role: str, user_id: str = "generic-user-1") -> dict:
    """Build headers for an arbitrary role string (used by RBAC matrices)."""
    return build_user_headers(user_id, role)
