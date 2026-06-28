"""Pre-built role headers for every role in the PRD (§2.1).

Only the Learner role is entity_backed (X-User-ID is the acting Learner.id);
ContentAdmin, ExamProctor, and PlatformOps are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for Learner tests that do NOT
# exercise ownership (e.g. 401/403/404 paths).
TEST_USERS = {
    # entity_backed Learner: shared constant is a fallback for non-ownership tests only.
    "learner_headers": build_user_headers("test-learner-1", "Learner"),
    # opaque roles: shared constant is the canonical form.
    "content_admin_headers": build_user_headers("test-admin-1", "ContentAdmin"),
    "exam_proctor_headers": build_user_headers("test-proctor-1", "ExamProctor"),
    "platform_ops_headers": build_user_headers("test-ops-1", "PlatformOps"),
}


# Per-instance builder — REQUIRED for the entity_backed Learner role.
# Pass the actual Learner.id as user_id whenever the call is ownership-gated.
def make_learner_headers(user_id: str) -> dict:
    """For Learner (entity_backed:Learner). Pass the owning Learner.id as user_id
    for every ownership-gated enrollment-scoped call."""
    return build_user_headers(user_id, "Learner")


def make_content_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ContentAdmin")


def make_exam_proctor_headers(user_id: str = "test-proctor-1") -> dict:
    return build_user_headers(user_id, "ExamProctor")


def make_platform_ops_headers(user_id: str = "test-ops-1") -> dict:
    return build_user_headers(user_id, "PlatformOps")
