"""Pre-built role headers for every role in the PRD (§2.1, §4)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, admin-acted calls).
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "developer_headers": build_user_headers("test-developer-1", "Developer"),
    # opaque roles: shared constants are the canonical form.
    "queue_admin_headers": build_user_headers("test-queue-admin-1", "QueueAdministrator"),
    "study_engineer_headers": build_user_headers("test-study-engineer-1", "StudyEngineer"),
    "regulator_headers": build_user_headers("test-regulator-1", "Regulator"),
}


def make_developer_headers(user_id: str) -> dict:
    """For Developer (entity_backed:Developer). Pass the actual Developer.id as
    user_id whenever the call is ownership-gated (PRD §2.1: a Developer caller
    may only act on projects whose developer_id equals their X-User-ID)."""
    return build_user_headers(user_id, "Developer")


def make_queue_admin_headers(user_id: str = "test-queue-admin-1") -> dict:
    return build_user_headers(user_id, "QueueAdministrator")


def make_study_engineer_headers(user_id: str = "test-study-engineer-1") -> dict:
    return build_user_headers(user_id, "StudyEngineer")


def make_regulator_headers(user_id: str = "test-regulator-1") -> dict:
    return build_user_headers(user_id, "Regulator")
