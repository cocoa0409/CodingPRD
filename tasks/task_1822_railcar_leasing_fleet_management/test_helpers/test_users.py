"""Pre-built role headers for every role in the PRD (§2.1).

LesseeRep is entity-backed: its X-User-ID must equal the acting Lessee.id
whenever the call is ownership-gated (PRD §2.1). The shared
`lessee_rep_headers` entry is a fallback for tests that do not exercise
ownership (e.g. role-denial on an endpoint that does not list LesseeRep).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "system_admin_headers": build_user_headers("test-sysadmin-1", "SystemAdmin"),
    "lease_admin_headers": build_user_headers("test-leaseadmin-1", "LeaseAdmin"),
    "fleet_planner_headers": build_user_headers("test-planner-1", "FleetPlanner"),
    "maintenance_controller_headers": build_user_headers(
        "test-maint-1", "MaintenanceController"
    ),
    "billing_analyst_headers": build_user_headers("test-billing-1", "BillingAnalyst"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-1", "ComplianceOfficer"
    ),
    # Fallback only: safe for role-denial tests, NOT for ownership-gated calls.
    "lessee_rep_headers": build_user_headers("test-lesseerep-1", "LesseeRep"),
}


def make_lessee_rep_headers(lessee_id: str) -> dict:
    """LesseeRep is entity-backed (PRD §2.1): pass the owning Lessee.id as
    user_id whenever the call is ownership-gated (statement dispute, mileage
    report submit/resubmit, damage dispute, repair preauthorize)."""
    return build_user_headers(lessee_id, "LesseeRep")


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_lease_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LeaseAdmin")


def make_fleet_planner_headers(user_id: str) -> dict:
    """FleetPlanner with a specific operator id — needed for retirement SoD,
    where proposer_user_id is the creator's X-User-ID (PRD §2.8)."""
    return build_user_headers(user_id, "FleetPlanner")


def make_maintenance_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MaintenanceController")


def make_billing_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingAnalyst")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer with a specific operator id — needed for retirement
    SoD, where the approver's X-User-ID must differ from proposer_user_id
    (PRD §2.8)."""
    return build_user_headers(user_id, "ComplianceOfficer")
