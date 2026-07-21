"""Pre-built role headers for every role in the PRD (§2.1).

- StoreStaff and Public are opaque identities; their shared constants are the
  canonical form.
- Member is entity_backed:Member. The shared constant is a fallback usable only
  for tests that do NOT exercise ownership (e.g. 401/validation on bad input).
  Any ownership-gated call MUST use make_member_headers(member["id"]) so that
  X-User-ID equals the acting member's real id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "staff_headers": build_user_headers("staff-op-1", "StoreStaff"),
    "public_headers": build_user_headers("public-1", "Public"),
    # Fallback only — never use for an ownership-gated Member call.
    "member_headers": build_user_headers("member-fallback-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """Headers for a Member (entity_backed:Member). Pass the acting Member's real
    id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_staff_headers() -> dict:
    return TEST_USERS["staff_headers"]


def make_public_headers() -> dict:
    return TEST_USERS["public_headers"]
