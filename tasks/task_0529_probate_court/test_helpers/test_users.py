"""Pre-built role headers for every role in the PRD.

All three roles carry an opaque identity: X-User-ID is never compared to an
entity id. The ProbateJudge id is read only for the segregation-of-duties check
(compared to a representative's declared representative_user_id, itself a stored
string), and the PersonalRepresentative id may be compared against the appointed
representative's representative_user_id. Builders below let a test pass the exact
operator id a scenario needs.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — the canonical form for opaque roles.
TEST_USERS = {
    "clerk_headers": build_user_headers("clerk-1", "Clerk"),
    "judge_headers": build_user_headers("judge-1", "ProbateJudge"),
    "representative_headers": build_user_headers("pr-user-1", "PersonalRepresentative"),
}


def make_clerk_headers(user_id: str = "clerk-1") -> dict:
    """Headers for a Clerk acting under the given opaque operator id."""
    return build_user_headers(user_id, "Clerk")


def make_judge_headers(user_id: str = "judge-1") -> dict:
    """Headers for a ProbateJudge. Pass the operator id the segregation-of-duties
    check should read (must differ from the PR's representative_user_id on appoint,
    unless the test is deliberately exercising the self-appointment rejection)."""
    return build_user_headers(user_id, "ProbateJudge")


def make_representative_headers(user_id: str = "pr-user-1") -> dict:
    """Headers for a PersonalRepresentative. Pass the representative_user_id that
    the estate's appointed representative was created under so administration acts
    (allow/pay claims, appraise/marshal assets, etc.) are attributed correctly."""
    return build_user_headers(user_id, "PersonalRepresentative")
