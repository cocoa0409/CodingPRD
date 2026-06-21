"""Pre-built role headers for every role in the PRD (§2.1).

The system recognizes exactly four roles. Two bind to a persisted entity
(AccountOwner -> the acting Account's id; ProfileUser -> the acting Profile's
id) and two are opaque (PlatformAdmin, Anonymous). Ownership-gated calls MUST
use the per-instance builders with the real entity id; the shared constants are
only for opaque roles or tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests whose success does not
# depend on the caller owning the targeted resource (e.g. 401/403/404 cases).
TEST_USERS = {
    # Opaque roles: the shared constant IS the canonical form.
    "admin_headers": build_user_headers("admin-op-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests
    # only (it intentionally does not equal any real entity id).
    "owner_headers": build_user_headers("owner-fallback-1", "AccountOwner"),
    "profile_headers": build_user_headers("profile-fallback-1", "ProfileUser"),
}


# --- Per-instance builders — required for every entity_backed role ---


def make_admin_headers(user_id: str = "admin-op-1") -> dict:
    """PlatformAdmin (opaque). X-User-ID is an arbitrary operator identifier."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    """Anonymous (opaque, token-bearer). X-User-ID is non-persisted."""
    return build_user_headers(user_id, "Anonymous")


def make_owner_headers(account_id: str) -> dict:
    """AccountOwner (entity_backed:Account). Pass the real Account.id whenever
    the call is ownership-gated."""
    return build_user_headers(account_id, "AccountOwner")


def make_profile_headers(profile_id: str) -> dict:
    """ProfileUser (entity_backed:Profile). Pass the real Profile.id whenever
    the call is ownership-gated (streams, downloads, watch-progress)."""
    return build_user_headers(profile_id, "ProfileUser")
