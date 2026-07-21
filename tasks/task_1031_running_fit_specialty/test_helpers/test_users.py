"""Pre-built role headers for every role in the PRD (Section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (StoreManager, Anonymous) and for
# tests that do not exercise ownership. Member/Fitter shared entries are a
# fallback for non-ownership tests only; ownership-gated calls MUST use the
# per-instance builders below with the real entity id.
TEST_USERS = {
    "store_manager_headers": build_user_headers("test-manager-1", "StoreManager"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    "fitter_headers": build_user_headers("test-fitter-1", "Fitter"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_fitter_headers(user_id: str) -> dict:
    """For Fitter (entity_backed:Fitter). Pass the actual Fitter.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Fitter")


def store_manager_headers() -> dict:
    return TEST_USERS["store_manager_headers"]
