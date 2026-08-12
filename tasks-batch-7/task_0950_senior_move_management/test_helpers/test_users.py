"""Pre-built role headers for the eight declared roles.

Three roles are operators whose identity is opaque and never compared to any
entity's id: PLATFORM_ADMIN, MOVE_MANAGER and BILLING_ADMIN.  The remaining five
are entity-backed, so ownership-gated calls MUST use the per-instance builder
with the real entity id rather than the shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identities - the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("ops-platform-admin-1", "PLATFORM_ADMIN"),
    "move_manager_headers": build_user_headers("ops-move-manager-1", "MOVE_MANAGER"),
    "billing_admin_headers": build_user_headers("ops-billing-admin-1", "BILLING_ADMIN"),
    # Entity-backed identities - fallback only for tests that never reach the
    # ownership rung (bad payloads, unresolvable ids, role-list refusals).
    "client_headers": build_user_headers("test-client-1", "CLIENT"),
    "family_member_headers": build_user_headers("test-family-1", "FAMILY_MEMBER"),
    "power_of_attorney_headers": build_user_headers("test-poa-1", "POWER_OF_ATTORNEY"),
    "crew_lead_headers": build_user_headers("test-crew-lead-1", "CREW_LEAD"),
    "vendor_headers": build_user_headers("test-vendor-1", "VENDOR"),
}

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
MOVE_MANAGER = TEST_USERS["move_manager_headers"]
BILLING_ADMIN = TEST_USERS["billing_admin_headers"]


def make_client_headers(client_id: str) -> dict:
    """CLIENT is backed by a Client row; pass the acting Client's id."""
    return build_user_headers(client_id, "CLIENT")


def make_family_member_headers(portal_party_id: str) -> dict:
    """FAMILY_MEMBER is backed by a PortalParty row; pass the acting seat's id."""
    return build_user_headers(portal_party_id, "FAMILY_MEMBER")


def make_power_of_attorney_headers(portal_party_id: str) -> dict:
    """POWER_OF_ATTORNEY is backed by a PortalParty row; pass the acting seat's id."""
    return build_user_headers(portal_party_id, "POWER_OF_ATTORNEY")


def make_crew_lead_headers(crew_member_id: str) -> dict:
    """CREW_LEAD is backed by a CrewMember row; pass the acting member's id."""
    return build_user_headers(crew_member_id, "CREW_LEAD")


def make_vendor_headers(vendor_id: str) -> dict:
    """VENDOR is backed by a Vendor row; pass the acting vendor's id."""
    return build_user_headers(vendor_id, "VENDOR")


def headers_without_user_id(role: str) -> dict:
    """An authenticated request that deliberately omits X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = "anonymous") -> dict:
    """A request that deliberately carries no X-User-Role header at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


__all__ = [
    "TEST_USERS",
    "PLATFORM_ADMIN",
    "MOVE_MANAGER",
    "BILLING_ADMIN",
    "make_client_headers",
    "make_family_member_headers",
    "make_power_of_attorney_headers",
    "make_crew_lead_headers",
    "make_vendor_headers",
    "headers_without_user_id",
    "headers_without_role",
]
