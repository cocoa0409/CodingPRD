"""Pre-built role headers for every role in the PRD (§2.1).

AssetManager and TenantRepBroker carry opaque identifiers never compared to a
Party id; Landlord/Tenant/Subtenant/Assignee carry the acting Party's id and
MUST be built per-instance via the make_*_headers builders whenever the call
is ownership-gated (decide, respond, remind, terminate, sign).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    # Opaque operator id (PRD §2.1: not tied to any persisted entity).
    "asset_manager_headers": build_user_headers("asset-manager-1", "AssetManager"),
    # Opaque broker ids; the originating broker is recorded as broker_user_id.
    "broker_1_headers": build_user_headers("broker-1", "TenantRepBroker"),
    "broker_2_headers": build_user_headers("broker-2", "TenantRepBroker"),
    # Fallbacks for entity-backed roles — only for tests that never pass an
    # ownership gate (e.g., plain GETs). Ownership-gated calls must use the
    # per-instance builders below with the actual Party id.
    "landlord_headers": build_user_headers("test-landlord-1", "Landlord"),
    "tenant_headers": build_user_headers("test-tenant-1", "Tenant"),
    "subtenant_headers": build_user_headers("test-subtenant-1", "Subtenant"),
    "assignee_headers": build_user_headers("test-assignee-1", "Assignee"),
}

# Convenience aliases for the two opaque broker identities used as X-User-ID.
BROKER_1_ID = "broker-1"
BROKER_2_ID = "broker-2"


def make_broker_headers(user_id: str) -> dict:
    """TenantRepBroker headers with a specific opaque broker identifier."""
    return build_user_headers(user_id, "TenantRepBroker")


def make_landlord_headers(user_id: str) -> dict:
    """Landlord headers; pass the lease's landlord Party id for gated calls."""
    return build_user_headers(user_id, "Landlord")


def make_tenant_headers(user_id: str) -> dict:
    """Tenant headers; pass the lease's tenant Party id for gated calls."""
    return build_user_headers(user_id, "Tenant")


def make_subtenant_headers(user_id: str) -> dict:
    """Subtenant headers; pass the transfer's counterparty Party id to sign."""
    return build_user_headers(user_id, "Subtenant")


def make_assignee_headers(user_id: str) -> dict:
    """Assignee headers; pass the transfer's counterparty Party id to sign."""
    return build_user_headers(user_id, "Assignee")
