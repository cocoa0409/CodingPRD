"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (IntakeStaff, CrewCoordinator, StoreManager, Cashier,
WarehouseAdmin) may use the shared constants anywhere. Entity-backed roles
(Donor -> Donor.id, Contractor -> ContractorAccount.id, HazmatTechnician /
CrewLead -> CrewMember.id) MUST use the per-instance builders with the real
entity id whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — canonical shared constants.
    "intake_staff_headers": build_user_headers("intake-1", "IntakeStaff"),
    "crew_coordinator_headers": build_user_headers("coordinator-1", "CrewCoordinator"),
    "store_manager_headers": build_user_headers("manager-1", "StoreManager"),
    "cashier_headers": build_user_headers("cashier-1", "Cashier"),
    "warehouse_admin_headers": build_user_headers("admin-1", "WarehouseAdmin"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "donor_headers": build_user_headers("donor-1", "Donor"),
    "contractor_headers": build_user_headers("contractor-1", "Contractor"),
    "hazmat_technician_headers": build_user_headers("tech-1", "HazmatTechnician"),
    "crew_lead_headers": build_user_headers("lead-1", "CrewLead"),
}


def make_donor_headers(user_id: str) -> dict:
    """Donor (entity-backed: Donor). Pass the real Donor.id for ownership-gated calls."""
    return build_user_headers(user_id, "Donor")


def make_contractor_headers(user_id: str) -> dict:
    """Contractor (entity-backed: ContractorAccount). Pass the real account id."""
    return build_user_headers(user_id, "Contractor")


def make_hazmat_technician_headers(user_id: str) -> dict:
    """HazmatTechnician (entity-backed: CrewMember). Pass the real CrewMember.id —
    screenings record performed_by_crew_id from X-User-ID."""
    return build_user_headers(user_id, "HazmatTechnician")


def make_crew_lead_headers(user_id: str) -> dict:
    """CrewLead (entity-backed: CrewMember). Pass the real CrewMember.id."""
    return build_user_headers(user_id, "CrewLead")


def make_intake_staff_headers(user_id: str) -> dict:
    """IntakeStaff is opaque; distinct ids matter for the receiver/issuer
    segregation-of-duties check on tax receipts."""
    return build_user_headers(user_id, "IntakeStaff")


def make_store_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StoreManager")


def make_crew_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CrewCoordinator")


def make_cashier_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Cashier")


def make_warehouse_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarehouseAdmin")
