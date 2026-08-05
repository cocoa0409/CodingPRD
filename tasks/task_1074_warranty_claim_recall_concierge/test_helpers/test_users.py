"""Pre-built role headers for the Warranty-Claim & Recall Concierge API.

Two identity styles per the PRD (Section 2.1):
  - Opaque roles (Anonymous, ConciergeAgent, PlatformAdmin): X-User-ID is an
    arbitrary token not tied to any stored entity → shared constants are fine.
  - Entity-backed roles (HouseholdOwner, HouseholdMember → Member;
    ManufacturerAgent → Manufacturer): X-User-ID MUST be the real entity id when
    the call is ownership-gated → use the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that do not exercise ownership.
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-token-1", "Anonymous"),
    "concierge_headers": build_user_headers("cx-agent-1", "ConciergeAgent"),
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
}


# ─── Per-instance builders — required for every entity-backed role ────────────
def make_household_owner_headers(member_id: str) -> dict:
    """HouseholdOwner (entity_backed:Member). Pass the acting OWNER Member.id."""
    return build_user_headers(member_id, "HouseholdOwner")


def make_household_member_headers(member_id: str) -> dict:
    """HouseholdMember (entity_backed:Member). Pass the acting ADULT/MINOR Member.id."""
    return build_user_headers(member_id, "HouseholdMember")


def make_manufacturer_agent_headers(manufacturer_id: str) -> dict:
    """ManufacturerAgent (entity_backed:Manufacturer). Pass the acting Manufacturer.id."""
    return build_user_headers(manufacturer_id, "ManufacturerAgent")


def make_concierge_headers(user_id: str) -> dict:
    """ConciergeAgent (opaque). Distinct user_ids drive the segregation-of-duties rule."""
    return build_user_headers(user_id, "ConciergeAgent")


def make_platform_admin_headers(user_id: str = "platform-admin-1") -> dict:
    """PlatformAdmin (opaque operator identity)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_anonymous_headers(user_id: str = "anon-token-1") -> dict:
    """Anonymous (opaque self-service caller)."""
    return build_user_headers(user_id, "Anonymous")
