"""Pre-built role headers for every role in the PRD (§2.1).

TeamMember is entity-backed: when X-User-Role is TeamMember, X-User-ID is the
id of the acting TravelPartyMember. Fixtures must use make_team_member_headers()
with the real member id for ownership-gated calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, role-denial tests).
TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "TravelOpsAdmin"),
    "manager_headers": build_user_headers("test-manager-1", "TravelManager"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "TravelCoordinator"),
    "finance_headers": build_user_headers("test-finance-1", "TravelFinanceLead"),
    "equipment_headers": build_user_headers("test-equipment-1", "EquipmentManager"),
    "security_headers": build_user_headers("test-security-1", "SecurityOfficer"),
    "approver_headers": build_user_headers("test-approver-1", "VenueCredentialApprover"),
    "vendor_headers": build_user_headers("test-vendor-1", "VendorRep"),
    "any_headers": build_user_headers("test-any-1", "Any"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "team_member_headers": build_user_headers("test-member-1", "TeamMember"),
}


# Per-instance builders.
def make_team_member_headers(member_id: str) -> dict:
    """For TeamMember (entity_backed:TravelPartyMember). Pass the actual
    TravelPartyMember.id whenever the call is ownership-gated."""
    return build_user_headers(member_id, "TeamMember")


def make_ops_admin_headers(user_id: str = "test-ops-admin-1") -> dict:
    return build_user_headers(user_id, "TravelOpsAdmin")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "TravelManager")


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "TravelCoordinator")


def make_finance_headers(user_id: str = "test-finance-1") -> dict:
    return build_user_headers(user_id, "TravelFinanceLead")


def make_equipment_headers(user_id: str = "test-equipment-1") -> dict:
    return build_user_headers(user_id, "EquipmentManager")


def make_security_officer_headers(user_id: str) -> dict:
    """SecurityOfficer with a chosen identity (SoD tests need distinct users)."""
    return build_user_headers(user_id, "SecurityOfficer")


def make_approver_headers(user_id: str) -> dict:
    """VenueCredentialApprover with a chosen identity (SoD tests need distinct users)."""
    return build_user_headers(user_id, "VenueCredentialApprover")


def make_vendor_headers(user_id: str = "test-vendor-1") -> dict:
    return build_user_headers(user_id, "VendorRep")
