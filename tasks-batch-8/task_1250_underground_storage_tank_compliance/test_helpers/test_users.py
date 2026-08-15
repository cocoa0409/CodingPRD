"""Pre-built role headers for every role in the PRD (§2.1).

Identity binding (PRD §2.1):
- FacilityOwner / ContractorAdmin / StateRegulator / Any: opaque X-User-ID.
- Technician / ComplianceReviewer: X-User-ID must be the id of a Technician
  resource — use the per-instance builders with the real technician id whenever
  the call is ownership- or segregation-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque owner identities (FacilityOwner is entity-less; owner-1/owner-2 are
    # compared against Facility.owner_account_id, never against entity ids).
    "facility_owner_headers": build_user_headers("owner-1", "FacilityOwner"),
    "facility_owner_2_headers": build_user_headers("owner-2", "FacilityOwner"),
    # Opaque back-office identity.
    "contractor_admin_headers": build_user_headers("admin-1", "ContractorAdmin"),
    # Opaque agency identity.
    "state_regulator_headers": build_user_headers("regulator-1", "StateRegulator"),
    # Read-only shared capacity.
    "any_headers": build_user_headers("reader-1", "Any"),
    # Fallback Technician/Reviewer identities for tests that do NOT exercise
    # ownership or segregation (e.g. 404s, role denials). Never use these for
    # start/results/certify on a real order — use the builders below.
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "ComplianceReviewer"),
}


def make_owner_headers(user_id: str) -> dict:
    """FacilityOwner headers for a specific opaque owner account id."""
    return build_user_headers(user_id, "FacilityOwner")


def make_technician_headers(technician_id: str) -> dict:
    """Technician headers bound to a real Technician.id (PRD §2.1: X-User-ID is
    the id of the acting Technician resource). Required for start/results."""
    return build_user_headers(technician_id, "Technician")


def make_reviewer_headers(technician_id: str) -> dict:
    """ComplianceReviewer headers bound to a real Technician.id (PRD §2.1:
    reviewers are technicians acting in a certifying capacity). Required for
    certify so the segregation check compares real technician ids."""
    return build_user_headers(technician_id, "ComplianceReviewer")
