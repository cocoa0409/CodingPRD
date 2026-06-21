"""Pre-built role headers for every role in the PRD.

ComplianceAdmin is an opaque operator id (never compared to any employee row),
so its shared constant is the canonical form. Learner and Manager are
entity-backed: their X-User-ID must be the acting Employee's id, so ownership-
gated calls MUST use the per-instance builders below with the real employee id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#   - admin: opaque → canonical form.
#   - learner/manager: fallback ONLY for tests that do not exercise ownership
#     (e.g. 401/403 role-permission probes, 404-on-missing-resource).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ComplianceAdmin"),
    "learner_headers": build_user_headers("test-learner-1", "Learner"),
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """ComplianceAdmin (opaque). The id is not matched against any employee."""
    return build_user_headers(user_id, "ComplianceAdmin")


def make_learner_headers(user_id: str) -> dict:
    """For Learner (entity_backed:Employee). Pass the acting Employee.id as user_id
    whenever the call is ownership-gated (start / quiz-attempts / tracking-sessions)."""
    return build_user_headers(user_id, "Learner")


def make_manager_headers(user_id: str) -> dict:
    """For Manager (entity_backed:Employee). Pass the manager Employee.id as user_id."""
    return build_user_headers(user_id, "Manager")
