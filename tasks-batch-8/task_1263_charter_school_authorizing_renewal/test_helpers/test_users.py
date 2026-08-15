"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "applicant_headers": build_user_headers("applicant_1", "Applicant"),
    "staff_headers": build_user_headers("staff_1", "AuthorizerStaff"),
    "reviewer_headers": build_user_headers("rev_1", "ApplicationReviewer"),
    "board_headers": build_user_headers("board_1", "BoardMember"),
    "appeals_officer_headers": build_user_headers("officer_1", "AppealsOfficer"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "school_operator_headers": build_user_headers("test-school-operator-1", "SchoolOperator"),
    "admin_headers": build_user_headers("admin_1", "AuthorizerAdmin"),
}


# Per-instance builders — required for ownership-gated or identity-recorded calls.
def make_applicant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Applicant")


def make_staff_headers(user_id: str) -> dict:
    """AuthorizerStaff with a specific X-User-ID (issuer/resolver SOD, submitter stamps)."""
    return build_user_headers(user_id, "AuthorizerStaff")


def make_reviewer_headers(user_id: str) -> dict:
    """ApplicationReviewer with a specific X-User-ID (rubric scorer / panelist)."""
    return build_user_headers(user_id, "ApplicationReviewer")


def make_board_headers(user_id: str) -> dict:
    """BoardMember with a specific X-User-ID (decider tracking, appeal SOD)."""
    return build_user_headers(user_id, "BoardMember")


def make_appeals_officer_headers(user_id: str) -> dict:
    """AppealsOfficer with a specific X-User-ID (assigned hearing officer)."""
    return build_user_headers(user_id, "AppealsOfficer")


def make_school_operator_headers(school_id: str) -> dict:
    """For SchoolOperator (entity_backed:School). Pass the actual School.id as
    school_id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(school_id, "SchoolOperator")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AuthorizerAdmin")
