"""Pre-built role headers for the four PRD roles (PRD §2.1).

ProgramAdmin and IntakeCoordinator carry opaque identities, so shared constants are
canonical for them. Volunteer and Applicant are entity-backed: ownership checks compare
X-User-ID against the row's foreign key, so any ownership-gated call MUST be made with
make_volunteer_headers(volunteer["id"]) / make_applicant_headers(applicant["id"]) built
from the actual entity id — the shared constants for those two roles are fallbacks for
tests that do not exercise ownership (e.g. role-denied probes).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — canonical shared constants
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "intake_coordinator_headers": build_user_headers("test-coordinator-1", "IntakeCoordinator"),
    # entity-backed roles — fallback only for non-ownership tests
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


def make_volunteer_headers(volunteer_id: str) -> dict:
    """Entity-backed Volunteer headers. Pass the real Volunteer.id whenever the call
    is ownership-gated (workshop complete, mock interview score, attendance append)."""
    return build_user_headers(volunteer_id, "Volunteer")


def make_applicant_headers(applicant_id: str) -> dict:
    """Entity-backed Applicant headers. Pass the real Applicant.id whenever the call
    is ownership-gated (self reads, own enrollments/seats/waivers/mocks/cases)."""
    return build_user_headers(applicant_id, "Applicant")
