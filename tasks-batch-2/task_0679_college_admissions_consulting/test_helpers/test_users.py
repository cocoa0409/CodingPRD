"""Pre-built role headers for every role in the PRD.

Roles:
  - Counselor (entity_backed:Counselor) — X-User-ID must equal the acting Counselor.id
  - Student   (entity_backed:Student)   — X-User-ID must equal the acting Student.id
  - PlatformAdmin (opaque)              — X-User-ID is an opaque operator id, never owns anything

For ownership-gated calls, use the per-instance builders below with the
real entity id (e.g. make_counselor_headers(counselor["id"])). The shared
TEST_USERS constants are safe only for non-ownership tests (e.g. PlatformAdmin
calls, or 401-unauthenticated tests).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque PlatformAdmin and non-ownership scenarios.
TEST_USERS = {
    # PlatformAdmin is opaque: the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # entity_backed roles: these are fallbacks only — never use for ownership-gated calls.
    "counselor_headers": build_user_headers("test-counselor-1", "Counselor"),
    "student_headers": build_user_headers("test-student-1", "Student"),
}


def make_counselor_headers(user_id: str) -> dict:
    """For Counselor (entity_backed:Counselor). Pass the real Counselor.id as user_id
    whenever the call is ownership-gated (the common case)."""
    return build_user_headers(user_id, "Counselor")


def make_student_headers(user_id: str) -> dict:
    """For Student (entity_backed:Student). Pass the real Student.id as user_id
    whenever the call is ownership-gated (the common case)."""
    return build_user_headers(user_id, "Student")


def make_admin_headers() -> dict:
    """PlatformAdmin headers (opaque identity)."""
    return TEST_USERS["platform_admin_headers"]


def make_unknown_role_headers(user_id: str = "ghost-1") -> dict:
    """Headers carrying an unrecognized X-User-Role, for ERR_UNAUTHENTICATED tests."""
    return build_user_headers(user_id, "Ghost")
