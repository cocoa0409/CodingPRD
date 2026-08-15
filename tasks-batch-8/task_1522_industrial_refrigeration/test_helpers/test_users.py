"""Pre-built role headers for every role in the PRD (section 2.1).

FacilityAdmin, PsCoordinator, MaintenanceLead and ComplianceOfficer are
opaque roles: X-User-ID is never compared to any entity id, so the shared
constants below are their canonical form.

Operator and ContractorRep are entity-backed: X-User-ID must be the id of an
existing Employee / Contractor respectively, and ownership-pinned endpoints
compare it against the resource's employee/contractor field. For those roles
the make_*_headers builders MUST be called with the real entity id; the
shared constants are fallbacks only for tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "facility_admin_headers": build_user_headers("test-facility-admin-1", "FacilityAdmin"),
    "ps_coordinator_headers": build_user_headers("test-ps-coordinator-1", "PsCoordinator"),
    "maintenance_lead_headers": build_user_headers("test-maintenance-lead-1", "MaintenanceLead"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    # Entity-backed roles — fallback only; prefer the builders below with a
    # real Employee.id / Contractor.id for any ownership-gated call.
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    "contractor_rep_headers": build_user_headers("test-contractor-rep-1", "ContractorRep"),
}


def make_operator_headers(employee_id: str) -> dict:
    """Operator is entity-backed by Employee: pass the real Employee.id."""
    return build_user_headers(employee_id, "Operator")


def make_contractor_rep_headers(contractor_id: str) -> dict:
    """ContractorRep is entity-backed by Contractor: pass the real Contractor.id."""
    return build_user_headers(contractor_id, "ContractorRep")


def make_facility_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FacilityAdmin")


def make_ps_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PsCoordinator")


def make_maintenance_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MaintenanceLead")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
