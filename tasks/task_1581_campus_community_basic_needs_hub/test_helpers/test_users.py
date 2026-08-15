"""Role headers for the nine PRD roles (§2.1).

Opaque roles (Anonymous, HubAdmin) get shared constants — their X-User-ID is never
resolved against a persisted entity at authentication time. Entity-backed roles
(Client, the five staff roles, PartnerAgencyRep) get per-instance builders: their
X-User-ID must be the actual entity id or authentication fails with
ERR_UNAUTHENTICATED, so a shared constant would never resolve.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles only.
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-visitor-1", "Anonymous"),
    "hub_admin_headers": build_user_headers("admin-1", "HubAdmin"),
}


def make_hub_admin_headers(operator_id: str = "admin-1") -> dict:
    """HubAdmin is opaque: any operator identifier authenticates. The grant
    two-person rule compares this id against the application's reviewed_by."""
    return build_user_headers(operator_id, "HubAdmin")


def make_client_headers(client_id: str) -> dict:
    """Client is entity_backed: pass the actual Client.id."""
    return build_user_headers(client_id, "Client")


def make_intake_coordinator_headers(staff_id: str) -> dict:
    """IntakeCoordinator is entity_backed: pass the StaffMember.id."""
    return build_user_headers(staff_id, "IntakeCoordinator")


def make_pantry_staff_headers(staff_id: str) -> dict:
    """PantryStaff is entity_backed: pass the StaffMember.id."""
    return build_user_headers(staff_id, "PantryStaff")


def make_benefits_counselor_headers(staff_id: str) -> dict:
    """BenefitsCounselor is entity_backed: pass the StaffMember.id."""
    return build_user_headers(staff_id, "BenefitsCounselor")


def make_grant_reviewer_headers(staff_id: str) -> dict:
    """GrantReviewer is entity_backed: pass the StaffMember.id."""
    return build_user_headers(staff_id, "GrantReviewer")


def make_shelter_coordinator_headers(staff_id: str) -> dict:
    """ShelterCoordinator is entity_backed: pass the StaffMember.id."""
    return build_user_headers(staff_id, "ShelterCoordinator")


def make_partner_agency_rep_headers(agency_id: str) -> dict:
    """PartnerAgencyRep is entity_backed: pass the PartnerAgency.id."""
    return build_user_headers(agency_id, "PartnerAgencyRep")
