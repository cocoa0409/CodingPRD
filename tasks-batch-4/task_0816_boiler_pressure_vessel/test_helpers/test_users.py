"""Pre-built role headers for every role in the PRD.

JurisdictionAdmin is an opaque operator identity; Owner and Inspector are
entity-backed, so ownership-gated calls MUST thread the real entity id via the
per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque JurisdictionAdmin, and for tests that
# do not exercise ownership (e.g. 401/403/404 checks).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "JurisdictionAdmin"),
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
}


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """Opaque JurisdictionAdmin identity (never compared to any entity id)."""
    return build_user_headers(user_id, "JurisdictionAdmin")


def make_owner_headers(user_id: str) -> dict:
    """For Owner (entity_backed:Owner). Pass the actual Owner.id whenever the
    call is ownership-gated (vessel/repair-order/fee-invoice/incident)."""
    return build_user_headers(user_id, "Owner")


def make_inspector_headers(user_id: str) -> dict:
    """For Inspector (entity_backed:Inspector). Pass the actual Inspector.id
    whenever the call is ownership-gated (recording an inspection result)."""
    return build_user_headers(user_id, "Inspector")
