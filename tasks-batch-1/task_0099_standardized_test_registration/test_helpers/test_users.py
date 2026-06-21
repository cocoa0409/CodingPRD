"""Pre-built role headers for every role in the PRD (§2.1).

Candidate is entity-backed: when X-User-Role is Candidate, X-User-ID must be the
acting Candidate's id, and ownership checks compare a resource's candidate FK to
X-User-ID. The other three roles (TestCenterAdmin, AccommodationReviewer,
ScoreOps) are opaque: X-User-ID is an operator identifier the server does not
match against any stored entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for Candidate-role tests that do
# NOT exercise ownership (e.g. 400-on-bad-payload, 404-on-missing-resource,
# 401/403 auth probes). For ownership-gated Candidate calls use the per-instance
# builder make_candidate_headers(candidate_id) with the real candidate id.
TEST_USERS = {
    "candidate_headers": build_user_headers("test-candidate-1", "Candidate"),
    "test_center_admin_headers": build_user_headers("test-admin-1", "TestCenterAdmin"),
    "accommodation_reviewer_headers": build_user_headers("test-reviewer-1", "AccommodationReviewer"),
    "score_ops_headers": build_user_headers("test-scoreops-1", "ScoreOps"),
}


# Per-instance builder — REQUIRED for the entity-backed Candidate role. Pass the
# actual Candidate.id as user_id whenever the call is ownership-gated.
def make_candidate_headers(candidate_id: str) -> dict:
    """For Candidate (entity_backed:Candidate). Pass the real Candidate.id as
    user_id whenever the call is ownership-gated (register, confirm, cancel,
    cancel-score, accommodation submit/resubmit, standby join/claim/decline,
    score-send, clep-claim)."""
    return build_user_headers(candidate_id, "Candidate")


# Opaque-role builders for symmetry; X-User-ID value is immaterial.
def make_test_center_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "TestCenterAdmin")


def make_accommodation_reviewer_headers(user_id: str = "test-reviewer-1") -> dict:
    return build_user_headers(user_id, "AccommodationReviewer")


def make_score_ops_headers(user_id: str = "test-scoreops-1") -> dict:
    return build_user_headers(user_id, "ScoreOps")
