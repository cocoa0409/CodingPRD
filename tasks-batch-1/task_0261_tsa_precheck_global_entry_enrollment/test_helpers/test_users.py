"""Pre-built role headers for every role in the PRD.

The six roles are Applicant, VettingOfficer, EnrollmentOfficer, AppealsOfficer,
SchedulingAdmin, and Auditor. Only Applicant is entity-backed: its X-User-ID
must equal the acting Applicant entity's id for ownership checks to pass.
The other five carry an opaque operator identifier not tied to any entity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for Applicant tests that do not
# exercise ownership (e.g. 401/403/404/422 on missing or mis-typed resources).
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    # opaque roles: shared constant is the canonical form.
    "vetting_officer_headers": build_user_headers("vetting-officer-1", "VettingOfficer"),
    "enrollment_officer_headers": build_user_headers("enrollment-officer-1", "EnrollmentOfficer"),
    "appeals_officer_headers": build_user_headers("appeals-officer-9", "AppealsOfficer"),
    "scheduling_admin_headers": build_user_headers("scheduling-admin-1", "SchedulingAdmin"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
}


# Per-instance builder — required for the entity_backed Applicant role.
def make_applicant_headers(user_id: str) -> dict:
    """For the Applicant role (entity_backed:Applicant). Pass the actual
    Applicant.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Applicant")


# Convenience builders for opaque roles where a specific operator id matters
# (e.g. segregation-of-duties tests pin the vetting and appeals officer ids).
def make_vetting_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VettingOfficer")


def make_appeals_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AppealsOfficer")
