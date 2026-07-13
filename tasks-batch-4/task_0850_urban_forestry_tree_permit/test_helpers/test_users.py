"""Pre-built role headers for every role in the PRD.

Five roles carry an opaque identity (ForestryAdmin, ForestryStaff, Arborist, Inspector,
Applicant); the Applicant's opaque X-User-ID is what a permit records as requested_by_user_id
for ownership. The Contractor role is entity_backed: its X-User-ID is the id of a Contractor
entity, so ownership-gated calls MUST use make_contractor_headers(<contractor.id>).
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable opaque applicant identities used across ownership tests.
APPLICANT_1 = "applicant-1"
APPLICANT_2 = "applicant-2"

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    "forestry_admin_headers": build_user_headers("test-admin-1", "ForestryAdmin"),
    "forestry_staff_headers": build_user_headers("test-staff-1", "ForestryStaff"),
    "arborist_headers": build_user_headers("test-arborist-1", "Arborist"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "applicant_headers": build_user_headers(APPLICANT_1, "Applicant"),
    # entity_backed role: shared constant is a fallback for non-ownership (GET) tests only.
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}


def make_contractor_headers(contractor_id: str) -> dict:
    """For a Contractor (entity_backed). Pass the actual Contractor.id whenever the
    call is ownership-gated (work-order start/complete, dig-ticket create)."""
    return build_user_headers(contractor_id, "Contractor")


def make_applicant_headers(user_id: str) -> dict:
    """For an Applicant. Pass the opaque X-User-ID that must match permit.requested_by_user_id
    on ownership-gated permit operations."""
    return build_user_headers(user_id, "Applicant")


def unauthenticated_headers() -> dict:
    """Headers whose X-User-Role is not a known role -> ERR_UNAUTHENTICATED."""
    return build_user_headers("nobody-1", "Nobody")
