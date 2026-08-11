"""Pre-built role headers for every role in the PRD.

Entity-backed roles (Client, FamilyMember, Driver) MUST be built per-instance
via the make_*_headers builders with the real entity id; the shared constants
below are only for calls that are not ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "coordinator_headers": build_user_headers("coord-1", "Coordinator"),
    "compliance_officer_headers": build_user_headers("rev-1", "ComplianceOfficer"),
    "billing_admin_headers": build_user_headers("bill-1", "BillingAdmin"),
    # Entity-backed roles: fallback for non-ownership tests only.
    "client_headers": build_user_headers("test-client-1", "Client"),
    "family_member_headers": build_user_headers("test-family-1", "FamilyMember"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Client")


def make_family_member_headers(user_id: str) -> dict:
    """For FamilyMember (entity_backed:FamilyMember). Pass the actual
    FamilyMember.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "FamilyMember")


def make_driver_headers(user_id: str) -> dict:
    """For Driver (entity_backed:Driver). Pass the actual Driver.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Driver")


def make_coordinator_headers(user_id: str) -> dict:
    """Opaque role; distinct user ids matter for segregation-of-duties setups
    (the dispatcher's id is recorded as matched_by_user_id)."""
    return build_user_headers(user_id, "Coordinator")


def make_billing_admin_headers(user_id: str) -> dict:
    """Opaque role; distinct user ids matter for segregation-of-duties checks
    on dispute resolution."""
    return build_user_headers(user_id, "BillingAdmin")


def make_compliance_officer_headers(user_id: str) -> dict:
    """Opaque role; the reviewer id is recorded as reviewed_by_user_id."""
    return build_user_headers(user_id, "ComplianceOfficer")
