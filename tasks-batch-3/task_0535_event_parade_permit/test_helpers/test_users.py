"""Pre-built role headers for every role in the PRD (§2.1).

Three roles: Applicant (entity_backed:Applicant), DepartmentReviewer (opaque,
X-User-ID encodes department context), PermitOfficer (opaque).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles (PermitOfficer, DepartmentReviewer),
# and for Applicant tests that do NOT exercise ownership (e.g. 400/404 checks).
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "officer_headers": build_user_headers("officer-1", "PermitOfficer"),
    # DepartmentReviewer X-User-ID encodes the department context.
    "police_headers": build_user_headers("POLICE", "DepartmentReviewer"),
    "fire_headers": build_user_headers("FIRE", "DepartmentReviewer"),
    "ems_headers": build_user_headers("EMS", "DepartmentReviewer"),
    "public_works_headers": build_user_headers("PUBLIC_WORKS", "DepartmentReviewer"),
    # entity_backed Applicant: shared constant is a fallback for non-ownership tests only.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


# Per-instance builders — required for the entity_backed Applicant role.
def make_applicant_headers(user_id: str) -> dict:
    """For Applicant (entity_backed:Applicant). Pass the actual Applicant.id as
    user_id for any ownership-gated call (applicant_user_id == X-User-ID)."""
    return build_user_headers(user_id, "Applicant")


def make_reviewer_headers(department: str) -> dict:
    """For DepartmentReviewer (opaque). X-User-ID encodes the department context
    (POLICE | FIRE | EMS | PUBLIC_WORKS); the server matches it to the review's
    department."""
    return build_user_headers(department, "DepartmentReviewer")


def officer_headers() -> dict:
    return TEST_USERS["officer_headers"]
