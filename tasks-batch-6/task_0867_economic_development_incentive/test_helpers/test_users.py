"""Pre-built role headers for every role in the PRD (§2.1).

All five roles are opaque: X-User-ID is a free-form operator identifier that the server
never compares against any row's id. Ownership checks compare X-User-ID against a recorded
owner identifier (applicant_user_id, reviewer_user_id, certified_by). The shared constants
below are the canonical form for every role; the per-id builders let a test drive ownership
and four-eyes segregation-of-duties with explicit identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "applicant_headers": build_user_headers("applicant-1", "Applicant"),
    "analyst_headers": build_user_headers("analyst-1", "ProgramAnalyst"),
    "director_headers": build_user_headers("director-1", "ProgramDirector"),
    "officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "public_headers": build_user_headers("public-1", "PublicViewer"),
}


def make_applicant_headers(user_id: str) -> dict:
    """Applicant with an explicit X-User-ID. Ownership-gated calls (submit, resubmit,
    dispute) must use the same id that was recorded as applicant_user_id."""
    return build_user_headers(user_id, "Applicant")


def make_analyst_headers(user_id: str) -> dict:
    """ProgramAnalyst with an explicit X-User-ID. The four-eyes control pins this id as
    the eligibility review's reviewer_user_id."""
    return build_user_headers(user_id, "ProgramAnalyst")


def make_director_headers(user_id: str) -> dict:
    """ProgramDirector with an explicit X-User-ID. Approval compares this id against the
    review's reviewer_user_id for segregation of duties."""
    return build_user_headers(user_id, "ProgramDirector")


def make_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
