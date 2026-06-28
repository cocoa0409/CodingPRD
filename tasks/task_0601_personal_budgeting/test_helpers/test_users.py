"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # PlatformAdmin: opaque role — X-User-ID not tied to any entity (PRD §2.1).
    "platform_admin_headers": build_user_headers("admin-operator-1", "PlatformAdmin"),
    # entity_backed roles: shared constants are fallbacks for NON-ownership tests only
    # (e.g. 401-missing-role variants, generic 404). Ownership-gated calls MUST use the
    # per-instance builders below with the real Member.id.
    "household_owner_headers": build_user_headers("placeholder-owner", "HouseholdOwner"),
    "household_member_headers": build_user_headers("placeholder-member", "HouseholdMember"),
}


def make_owner_headers(member_id: str) -> dict:
    """For HouseholdOwner (entity_backed:Member). Pass the founding Member.id
    (owner_member_id) whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(member_id, "HouseholdOwner")


def make_member_headers(member_id: str) -> dict:
    """For HouseholdMember (entity_backed:Member). Pass the invited Member.id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(member_id, "HouseholdMember")


def admin_headers() -> dict:
    """PlatformAdmin headers (opaque operator)."""
    return TEST_USERS["platform_admin_headers"]
