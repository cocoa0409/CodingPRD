"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the opaque SchoolAdmin role, and for tests that do
# not exercise per-resource ownership (e.g. 401/403/404 on missing or
# wrong-role calls). entity_backed roles below also expose per-instance builders
# that MUST be used whenever the call is ownership-gated.
TEST_USERS = {
    # SchoolAdmin: opaque identity — shared constant is the canonical form.
    "admin_headers": build_user_headers("admin-operator-1", "SchoolAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests
    # (e.g. forbidden-role checks where the call is rejected before ownership).
    "student_headers": build_user_headers("test-student-1", "Student"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "guardian_headers": build_user_headers("test-guardian-1", "Guardian"),
}


# ---------------------------------------------------------------------------
# Per-instance builders — required for every entity_backed role. Pass the real
# entity id so ownership checks (§2.1) compare X-User-ID to a live entity.
# ---------------------------------------------------------------------------
def make_admin_headers(user_id: str = "admin-operator-1") -> dict:
    """SchoolAdmin (opaque). Any non-empty operator id is accepted."""
    return build_user_headers(user_id, "SchoolAdmin")


def make_student_headers(student_id: str) -> dict:
    """For Student (entity_backed:Student). Pass the Student.id as user_id for
    ownership-gated calls (own enrollments, lessons, certificates, etc.)."""
    return build_user_headers(student_id, "Student")


def make_instructor_headers(instructor_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the Instructor.id as
    user_id for ownership-gated calls (completing own lessons, payout summary)."""
    return build_user_headers(instructor_id, "Instructor")


def make_guardian_headers(consent_id: str) -> dict:
    """For Guardian (entity_backed:GuardianConsent). Pass the GuardianConsent.id
    as user_id for grant/revoke and ward-portal calls."""
    return build_user_headers(consent_id, "Guardian")


def make_anonymous_headers() -> dict:
    """No auth headers at all — drives ERR_UNAUTHENTICATED."""
    return {}
