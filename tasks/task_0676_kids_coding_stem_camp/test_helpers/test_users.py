"""Pre-built role headers for every role in the PRD (PRD §2.1).

CenterAdmin and Instructor identities are opaque operator identifiers that the
server never compares to any entity id, so the shared constants are canonical
for them. Guardian identity is entity_backed: X-User-ID must equal the acting
Guardian's id for ownership-gated operations, so a per-instance builder is
provided and MUST be used whenever a call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "center_admin_headers": build_user_headers("test-center-admin-1", "CenterAdmin"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    # entity_backed Guardian: this shared constant is a fallback usable only for
    # tests that do NOT exercise ownership (e.g. a Guardian with an unknown role
    # check). Ownership-gated calls MUST use make_guardian_headers(guardian_id).
    "guardian_headers": build_user_headers("test-guardian-1", "Guardian"),
}


def make_center_admin_headers(user_id: str = "test-center-admin-1") -> dict:
    """CenterAdmin headers (opaque identity)."""
    return build_user_headers(user_id, "CenterAdmin")


def make_instructor_headers(user_id: str = "test-instructor-1") -> dict:
    """Instructor headers (opaque identity)."""
    return build_user_headers(user_id, "Instructor")


def make_guardian_headers(guardian_id: str) -> dict:
    """Guardian headers (entity_backed:Guardian). Pass the actual Guardian.id as
    user_id whenever the call is ownership-gated (member/membership/enrollment/
    showcase-entry create, cancel, progress read, withdraw, etc.)."""
    return build_user_headers(guardian_id, "Guardian")
