"""Pre-built role headers for every role in the PRD.

Opaque roles (PlatformAdmin, PropertyManager, Anonymous) use shared-constant headers.
Entity-backed roles (Owner, Guest, Vendor) additionally expose a per-instance builder
that must be called with the actual entity id whenever the downstream call is
ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque roles — shared constants are the canonical form
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "property_manager_headers": build_user_headers("test-pm-1", "PropertyManager"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # entity-backed roles — shared constants are a fallback for NON-ownership tests only
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
}


def make_owner_headers(user_id: str) -> dict:
    """For Owner (entity_backed:Owner). Pass the actual Owner.id for ownership-gated calls."""
    return build_user_headers(user_id, "Owner")


def make_guest_headers(user_id: str) -> dict:
    """For Guest (entity_backed:Guest). Pass the actual Guest.id for ownership-gated calls."""
    return build_user_headers(user_id, "Guest")


def make_vendor_headers(user_id: str) -> dict:
    """For Vendor (entity_backed:Vendor). Pass the actual Vendor.id for ownership-gated calls."""
    return build_user_headers(user_id, "Vendor")
