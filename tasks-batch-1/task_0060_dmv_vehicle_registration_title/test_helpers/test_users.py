"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# ClerkAgent, InspectionStation, DmvAdmin are opaque roles: X-User-ID is an opaque
# operator id not tied to any entity, so the shared constant is the canonical form.
# Owner is entity_backed:Owner — the shared constant is a fallback for non-ownership
# tests only; ownership-gated calls must use make_owner_headers(owner["id"]).
TEST_USERS = {
    "clerk_headers": build_user_headers("clerk-agent-1", "ClerkAgent"),
    "inspection_headers": build_user_headers("inspection-station-1", "InspectionStation"),
    "admin_headers": build_user_headers("dmv-admin-1", "DmvAdmin"),
    "owner_headers": build_user_headers("owner-fallback-1", "Owner"),
}


def make_owner_headers(user_id: str) -> dict:
    """For Owner (entity_backed:Owner). Pass the actual Owner.id as user_id whenever
    the call is ownership-gated."""
    return build_user_headers(user_id, "Owner")


def make_clerk_headers(user_id: str = "clerk-agent-1") -> dict:
    return build_user_headers(user_id, "ClerkAgent")


def make_inspection_headers(user_id: str = "inspection-station-1") -> dict:
    return build_user_headers(user_id, "InspectionStation")


def make_admin_headers(user_id: str = "dmv-admin-1") -> dict:
    return build_user_headers(user_id, "DmvAdmin")
