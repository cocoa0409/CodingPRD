"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# resource ownership. PlatformAdmin, Underwriter, CollectionsAgent, and
# CollectionsManager are all opaque identities (X-User-ID not compared to any
# entity id), so their shared constants are the canonical form.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "underwriter_headers": build_user_headers("underwriter-1", "Underwriter"),
    "collections_agent_headers": build_user_headers("agent-1", "CollectionsAgent"),
    "collections_manager_headers": build_user_headers("manager-1", "CollectionsManager"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "renter_headers": build_user_headers("renter-shared", "Renter"),
    "property_manager_headers": build_user_headers("property-shared", "PropertyManager"),
}


# ---- Per-instance builders (required for entity_backed roles) ----

def make_renter_headers(user_id: str) -> dict:
    """For Renter (entity_backed:Renter). Pass the actual Renter.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Renter")


def make_property_manager_headers(user_id: str) -> dict:
    """For PropertyManager (entity_backed:Property). Pass the actual Property.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "PropertyManager")


# ---- Opaque-role builders with a chosen X-User-ID (for SoD tests) ----

def make_agent_headers(user_id: str) -> dict:
    """CollectionsAgent with an explicit X-User-ID (stamped as last_recovery_agent_id)."""
    return build_user_headers(user_id, "CollectionsAgent")


def make_manager_headers(user_id: str) -> dict:
    """CollectionsManager with an explicit X-User-ID (SoD compared to last_recovery_agent_id)."""
    return build_user_headers(user_id, "CollectionsManager")
