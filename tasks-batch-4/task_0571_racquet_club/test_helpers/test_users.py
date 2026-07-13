"""Pre-built role headers for every role in the Racquet Club PRD (§2.1).

Two roles are entity_backed (Member -> Member.id, Pro -> Pro.id): ownership-gated
calls MUST use the per-instance builders so X-User-ID equals the real entity id.
FrontDesk is opaque and uses the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for FrontDesk (opaque) and for non-ownership tests.
TEST_USERS = {
    "frontdesk_headers": build_user_headers("frontdesk-op-1", "FrontDesk"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    "pro_headers": build_user_headers("test-pro-1", "Pro"),
}


def make_member_headers(user_id: str) -> dict:
    """For a Member (entity_backed:Member). Pass the actual Member.id whenever the
    call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_pro_headers(user_id: str) -> dict:
    """For a Pro (entity_backed:Pro). Pass the actual Pro.id whenever the call is
    ownership-gated."""
    return build_user_headers(user_id, "Pro")


def make_frontdesk_headers(user_id: str = "frontdesk-op-1") -> dict:
    """FrontDesk identity is opaque; user_id is not tied to any entity."""
    return build_user_headers(user_id, "FrontDesk")
