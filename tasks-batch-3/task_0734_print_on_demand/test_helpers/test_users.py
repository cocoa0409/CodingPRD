"""Pre-built role headers for every role in the PRD.

Roles:
- Anonymous     — opaque
- Creator       — entity_backed:Creator
- PlatformAdmin — opaque
- FulfillmentPartner — entity_backed:FulfillmentPartner
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for non-ownership tests only.
TEST_USERS = {
    # opaque roles: shared constant is canonical
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "creator_headers": build_user_headers("test-creator-fallback", "Creator"),
    "fulfillment_partner_headers": build_user_headers("test-partner-fallback", "FulfillmentPartner"),
}


# Per-instance builders — REQUIRED for entity_backed roles when ownership matters.

def make_creator_headers(creator_id: str) -> dict:
    """For Creator (entity_backed:Creator). Pass the actual Creator.id when the call
    is ownership-gated (any storefront/design/listing/order write on that creator's
    resources)."""
    return build_user_headers(creator_id, "Creator")


def make_fulfillment_partner_headers(partner_id: str) -> dict:
    """For FulfillmentPartner (entity_backed:FulfillmentPartner). Pass the actual
    FulfillmentPartner.id when driving job/order fulfillment transitions."""
    return build_user_headers(partner_id, "FulfillmentPartner")


def make_anonymous_headers(user_id: str = "test-anonymous") -> dict:
    """For Anonymous (opaque). The id is not compared to any entity."""
    return build_user_headers(user_id, "Anonymous")


def make_platform_admin_headers(user_id: str = "test-admin") -> dict:
    """For PlatformAdmin (opaque)."""
    return build_user_headers(user_id, "PlatformAdmin")
