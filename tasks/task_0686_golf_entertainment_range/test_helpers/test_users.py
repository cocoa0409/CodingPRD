"""Pre-built role headers for every role in the PRD (§2.1).

Three roles exist: Guest, FrontDesk, RangeManager.

- Guest is entity-backed: its X-User-ID is the id of the acting Member, and
  ownership checks compare a resource's member_id / organizer_member_id against
  it. Any ownership-gated Guest call MUST use make_guest_headers(member["id"])
  so X-User-ID equals the owning member's id. The shared TEST_USERS["guest_headers"]
  constant is a fallback only for Guest calls that do NOT exercise ownership
  (e.g. self-register, a 401/403/404 that fires before the ownership check).

- FrontDesk and RangeManager are opaque operators: X-User-ID is never compared
  to any entity id, so the shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
TEST_USERS = {
    # entity_backed Guest: shared fallback for non-ownership Guest calls only.
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
    # opaque operators: shared constants are canonical.
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    "range_manager_headers": build_user_headers("test-rangemanager-1", "RangeManager"),
}


def make_guest_headers(member_id: str) -> dict:
    """Guest headers whose X-User-ID is the acting Member.id. Use for every
    ownership-gated Guest call (own reservation/queue/lesson/event mutations)."""
    return build_user_headers(member_id, "Guest")


def make_front_desk_headers(user_id: str = "test-frontdesk-1") -> dict:
    """FrontDesk headers (opaque operator)."""
    return build_user_headers(user_id, "FrontDesk")


def make_range_manager_headers(user_id: str = "test-rangemanager-1") -> dict:
    """RangeManager headers (opaque operator)."""
    return build_user_headers(user_id, "RangeManager")
