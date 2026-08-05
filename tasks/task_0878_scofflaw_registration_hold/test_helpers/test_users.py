"""Pre-built role headers for every role in the PRD.

Only the Owner role is entity_backed: an Owner's X-User-ID must equal the acting
Owner entity's id for ownership-gated calls. The other four roles are opaque
operator identifiers, so a shared constant is the canonical form for each.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "enforcement_officer_headers": build_user_headers("eo-1", "EnforcementOfficer"),
    "hearing_clerk_headers": build_user_headers("clerk-1", "HearingClerk"),
    "collections_admin_headers": build_user_headers("collections-1", "CollectionsAdmin"),
    # Shared Owner constant — fallback for non-ownership tests only.
    "owner_headers": build_user_headers("owner-shared-1", "Owner"),
}


def make_owner_headers(user_id: str) -> dict:
    """For the entity_backed Owner role. Pass the actual Owner.id whenever the
    call is ownership-gated (disputes, payments, plans, waivers, release fees)."""
    return build_user_headers(user_id, "Owner")


def make_enforcement_headers(user_id: str) -> dict:
    """EnforcementOfficer (opaque). Distinct user_ids drive four-eyes SoD on
    boot/tow dispatch vs apply."""
    return build_user_headers(user_id, "EnforcementOfficer")
