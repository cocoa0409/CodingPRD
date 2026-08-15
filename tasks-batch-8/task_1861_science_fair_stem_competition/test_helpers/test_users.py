"""Pre-built role headers for every role in the PRD (§2.1).

Mentor and Judge are entity-backed roles: their X-User-ID must be the id of the
acting Mentor/Judge entity, so ownership-gated calls MUST go through the
per-instance builders below. The shared constants for those two roles are
fallbacks for tests that never exercise an ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "fair_director_headers": build_user_headers("test-fair-director-1", "FairDirector"),
    "ethics_reviewer_headers": build_user_headers("test-ethics-reviewer-1", "EthicsReviewer"),
    "operations_lead_headers": build_user_headers("test-operations-lead-1", "OperationsLead"),
    "safety_inspector_headers": build_user_headers("test-safety-inspector-1", "SafetyInspector"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "mentor_headers": build_user_headers("test-mentor-1", "Mentor"),
    "judge_headers": build_user_headers("test-judge-1", "Judge"),
}


def make_mentor_headers(user_id: str) -> dict:
    """For Mentor (entity-backed). Pass the actual Mentor.id as user_id
    whenever the call is ownership-gated (project/research-plan writes)."""
    return build_user_headers(user_id, "Mentor")


def make_judge_headers(user_id: str) -> dict:
    """For Judge (entity-backed). Pass the actual Judge.id as user_id
    whenever the call is ownership-gated (score submission, recusal)."""
    return build_user_headers(user_id, "Judge")
