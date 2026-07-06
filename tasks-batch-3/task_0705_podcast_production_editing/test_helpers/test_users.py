"""Pre-built role headers for every role in the PRD.

ShowOwner and ProducerEng are entity-backed: X-User-ID must equal the owning
Show.id / Engineer.id respectively for ownership-gated calls (PRD §2.1).
PlatformAdmin and AdOps are opaque operator identifiers not tied to any entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership (e.g. 401/403/404 probes, or PlatformAdmin/AdOps operations).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-op-1", "PlatformAdmin"),
    "ad_ops_headers": build_user_headers("adops-op-1", "AdOps"),
    # Fallback constants for entity-backed roles: use ONLY for non-ownership
    # tests. Ownership-gated calls MUST use the per-instance builders below.
    "show_owner_headers": build_user_headers("show-owner-fallback", "ShowOwner"),
    "producer_eng_headers": build_user_headers("producer-eng-fallback", "ProducerEng"),
}


def make_platform_admin_headers(user_id="admin-op-1"):
    """PlatformAdmin (opaque). X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_ad_ops_headers(user_id="adops-op-1"):
    """AdOps (opaque). X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "AdOps")


def make_show_owner_headers(show_id):
    """ShowOwner (entity_backed:Show). Pass the owning Show.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(show_id, "ShowOwner")


def make_producer_eng_headers(engineer_id):
    """ProducerEng (entity_backed:Engineer). Pass the acting Engineer.id as
    user_id whenever the call is ownership-gated (session ops)."""
    return build_user_headers(engineer_id, "ProducerEng")
