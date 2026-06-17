"""Pre-built role headers for every role in the PRD (§2.1).

Three roles: HousingOfficer (opaque operator identity), Student
(entity_backed:Student), and ResidentAdvisor (entity_backed:Student).

For ownership-gated calls by Student or ResidentAdvisor, the caller's
X-User-ID must equal the owning Student.id (the applicant, group owner,
resident, or the incident's reporter_student_id). Use the per-instance
builders below with the real Student.id whenever ownership is enforced.
The shared TEST_USERS constants are safe only for the opaque HousingOfficer
and for non-ownership tests (e.g. 401/403/404 negative paths).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator: shared constant is the canonical form.
    "housing_officer_headers": build_user_headers("test-officer-1", "HousingOfficer"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "student_headers": build_user_headers("test-student-1", "Student"),
    "resident_advisor_headers": build_user_headers("test-ra-1", "ResidentAdvisor"),
}


def make_officer_headers() -> dict:
    """HousingOfficer headers (opaque identity; not compared to any entity id)."""
    return TEST_USERS["housing_officer_headers"]


def make_student_headers(student_id: str) -> dict:
    """Student headers bound to a real Student.id.

    Pass the acting student's id whenever the call is ownership-gated
    (own application, group, membership, assignment, meal plan, break request).
    """
    return build_user_headers(student_id, "Student")


def make_ra_headers(student_id: str) -> dict:
    """ResidentAdvisor headers bound to a real Student.id.

    Pass the RA's own student id (it is compared to the incident report's
    reporter_student_id on incident operations).
    """
    return build_user_headers(student_id, "ResidentAdvisor")
