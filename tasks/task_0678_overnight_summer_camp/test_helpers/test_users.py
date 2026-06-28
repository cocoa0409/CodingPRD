"""Pre-built role headers for every role in the PRD.

Two of the four roles (CampDirector, InfirmaryNurse, Anonymous) bind to an
opaque, non-entity X-User-ID, so a shared constant is the canonical form for
them. The Guardian role is entity_backed (X-User-ID == Guardian.id), so its
ownership-gated calls MUST use the per-instance builder make_guardian_headers
with the actual Guardian.id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants. Safe for opaque roles (director/nurse/anonymous) and for
# tests that never exercise Guardian ownership (e.g. 401 / forbidden-role).
TEST_USERS = {
    "director_headers": build_user_headers("test-director-1", "CampDirector"),
    "nurse_headers": build_user_headers("test-nurse-1", "InfirmaryNurse"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Fallback only — never use for ownership-gated Guardian calls.
    "guardian_headers": build_user_headers("test-guardian-1", "Guardian"),
}


def make_director_headers(user_id: str = "test-director-1") -> dict:
    """CampDirector headers (opaque identity)."""
    return build_user_headers(user_id, "CampDirector")


def make_nurse_headers(user_id: str = "test-nurse-1") -> dict:
    """InfirmaryNurse headers (opaque identity)."""
    return build_user_headers(user_id, "InfirmaryNurse")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    """Anonymous headers (opaque identity)."""
    return build_user_headers(user_id, "Anonymous")


def make_guardian_headers(user_id: str) -> dict:
    """Guardian headers (entity_backed:Guardian). Pass the actual Guardian.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Guardian")
