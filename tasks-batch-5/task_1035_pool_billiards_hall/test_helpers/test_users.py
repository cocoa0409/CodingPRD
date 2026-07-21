"""Pre-built role headers for every role in the PRD (Section 2.1).

Roles:
  - Manager, FrontDesk, ProShopStaff — opaque operational roles (shared constants).
  - Member — entity-backed; X-User-ID must equal the acting Member's own id, so
    ownership-gated calls MUST use make_member_headers(member_id).
  - Anonymous — no authenticated headers (empty dict).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    "manager": build_user_headers("op-manager-1", "Manager"),
    "frontdesk": build_user_headers("op-frontdesk-1", "FrontDesk"),
    "proshop": build_user_headers("op-proshop-1", "ProShopStaff"),
    # Fallback Member constant — ONLY for non-ownership tests; ownership-gated calls
    # must use make_member_headers(member_id).
    "member": build_user_headers("test-member-1", "Member"),
}

# Anonymous / unauthenticated caller — no role headers at all.
ANON_HEADERS: dict = {}


def make_member_headers(member_id: str) -> dict:
    """Headers for an entity-backed Member. Pass the actual Member.id as user_id
    whenever the call is ownership-gated (own reservation/entry/event/plan-change)."""
    return build_user_headers(member_id, "Member")


def make_manager_headers(user_id: str = "op-manager-1") -> dict:
    return build_user_headers(user_id, "Manager")


def make_frontdesk_headers(user_id: str = "op-frontdesk-1") -> dict:
    return build_user_headers(user_id, "FrontDesk")


def make_proshop_headers(user_id: str = "op-proshop-1") -> dict:
    return build_user_headers(user_id, "ProShopStaff")
