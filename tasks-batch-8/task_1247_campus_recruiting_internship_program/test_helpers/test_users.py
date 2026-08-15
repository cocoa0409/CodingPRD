"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. Entity-backed roles must prefer the per-instance builders below
# whenever the call is ownership-gated.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "RecruitingAdmin"),
    "recruiter_headers": build_user_headers("test-recruiter-1", "Recruiter"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # entity_backed fallbacks — non-ownership contexts only:
    "candidate_headers": build_user_headers("test-candidate-1", "Candidate"),
    "evaluator_headers": build_user_headers("test-evaluator-1", "Evaluator"),
    "mentor_headers": build_user_headers("test-mentor-1", "Mentor"),
}


def make_candidate_headers(user_id: str) -> dict:
    """For Candidate (entity_backed:Candidate). Pass the actual Candidate.id
    whenever the call is ownership-gated (submit/withdraw/accept/decline/read-own)."""
    return build_user_headers(user_id, "Candidate")


def make_evaluator_headers(user_id: str) -> dict:
    """For Evaluator (entity_backed:Employee). Pass the actual Employee.id
    whenever the call is ownership-gated (submit/revise evaluation)."""
    return build_user_headers(user_id, "Evaluator")


def make_mentor_headers(user_id: str) -> dict:
    """For Mentor (entity_backed:Employee). Pass the actual Employee.id
    whenever the call is ownership-gated (submit intern evaluation)."""
    return build_user_headers(user_id, "Mentor")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "RecruitingAdmin")


def make_recruiter_headers(user_id: str = "test-recruiter-1") -> dict:
    return build_user_headers(user_id, "Recruiter")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
