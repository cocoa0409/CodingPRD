"""Pre-built role headers for every role in the PRD (§2.1).

The system recognizes exactly three roles: NetworkAdmin, LoungeAgent, Member.

- NetworkAdmin is an opaque operator: X-User-ID is not tied to any persisted
  entity, so a shared constant is the canonical form.
- LoungeAgent is entity_backed:Lounge — X-User-ID must equal the staffed
  lounge's id. Any agent action against a visit is ownership-gated
  (X-User-ID == Visit.lounge_id), so ownership-gated agent calls MUST use
  make_lounge_agent_headers(lounge["id"]) with the real Lounge id.
- Member is entity_backed:Member — X-User-ID must equal the member's id. Any
  member action on a visit/day-pass/card/shower reservation is ownership-gated,
  so ownership-gated member calls MUST use make_member_headers(member["id"]).

Falling back to a shared constant for an entity_backed role reproduces the
canonical bug: X-User-ID is a string that equals no real entity id, so every
ownership check rejects every request.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — canonical for the opaque NetworkAdmin, and safe for tests
# that do NOT exercise ownership (401/403/404 paths, or admin-driven setup).
TEST_USERS = {
    "network_admin_headers": build_user_headers("test-admin-1", "NetworkAdmin"),
    # Entity_backed shared fallbacks — for non-ownership tests only. Their
    # X-User-ID equals no real entity id, so they must NOT be used on
    # ownership-gated calls.
    "lounge_agent_headers": build_user_headers("test-agent-1", "LoungeAgent"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_network_admin_headers(user_id: str = "test-admin-1") -> dict:
    """Headers for a NetworkAdmin (opaque operator)."""
    return build_user_headers(user_id, "NetworkAdmin")


def make_lounge_agent_headers(user_id: str) -> dict:
    """For the LoungeAgent role (entity_backed:Lounge). Pass the actual Lounge.id
    as user_id whenever the call is ownership-gated (check-in/complete on a visit
    at that lounge, complete a shower reservation at that lounge)."""
    return build_user_headers(user_id, "LoungeAgent")


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (cancel own visit, purchase a
    day pass, activate own card, book/cancel own shower reservation)."""
    return build_user_headers(user_id, "Member")
