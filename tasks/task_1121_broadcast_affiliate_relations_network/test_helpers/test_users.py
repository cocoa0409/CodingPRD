"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# entity-backed ownership. StationGroupOwner is entity_backed:StationGroup,
# so ownership-gated calls MUST use make_station_group_owner_headers(sg_id).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "nar_headers": build_user_headers("test-nar-1", "NetworkAffiliateRelations"),
    # Fallback for non-ownership-gated StationGroupOwner calls.
    "sgo_headers": build_user_headers("test-sgo-fallback-1", "StationGroupOwner"),
    "auditor_headers": build_user_headers("test-auditor-1", "ComplianceAuditor"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_nar_headers(user_id: str = "test-nar-1") -> dict:
    return build_user_headers(user_id, "NetworkAffiliateRelations")


def make_station_group_owner_headers(station_group_id: str) -> dict:
    """StationGroupOwner is entity_backed:StationGroup (PRD §2.1). The
    X-User-ID must equal the owning StationGroup.id for ownership-gated calls."""
    return build_user_headers(station_group_id, "StationGroupOwner")


def make_auditor_headers(user_id: str = "test-auditor-1") -> dict:
    return build_user_headers(user_id, "ComplianceAuditor")
