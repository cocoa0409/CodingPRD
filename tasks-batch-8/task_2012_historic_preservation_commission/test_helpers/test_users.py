"""Pre-built role headers for every role in the PRD (§2.1).

PreservationStaff, Commissioner, CouncilMember, and EnforcementOfficer carry
opaque operator identifiers never compared to any entity id. Applicant is
entity-backed: when the call is ownership-gated, X-User-ID must be the acting
PropertyOwner's id — use make_applicant_headers(owner["id"]) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, staff-acted calls).
TEST_USERS = {
    "staff_headers": build_user_headers("test-staff-1", "PreservationStaff"),
    "commissioner_headers": build_user_headers("test-commissioner-1", "Commissioner"),
    "council_headers": build_user_headers("test-council-1", "CouncilMember"),
    "officer_headers": build_user_headers("test-officer-1", "EnforcementOfficer"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


def make_staff_headers(user_id: str = "test-staff-1") -> dict:
    """PreservationStaff with a specific opaque operator id. Segregation of
    duties (PRD §3.4) compares this id against completeness_accepted_by."""
    return build_user_headers(user_id, "PreservationStaff")


def make_commissioner_headers(user_id: str = "test-commissioner-1") -> dict:
    return build_user_headers(user_id, "Commissioner")


def make_council_headers(user_id: str = "test-council-1") -> dict:
    return build_user_headers(user_id, "CouncilMember")


def make_officer_headers(user_id: str = "test-officer-1") -> dict:
    return build_user_headers(user_id, "EnforcementOfficer")


def make_applicant_headers(owner_id: str) -> dict:
    """For Applicant (entity-backed by PropertyOwner). Pass the actual
    PropertyOwner.id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(owner_id, "Applicant")
