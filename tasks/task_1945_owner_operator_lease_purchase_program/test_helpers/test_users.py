"""Pre-built role headers for every role in the PRD (section 2.1).

The four carrier-side roles are opaque identities: the server does not compare
their X-User-ID to any entity id, so shared constants are canonical. Driver is
entity-backed: X-User-ID must equal the acting OwnerOperator's id, so ownership-
gated calls MUST use make_driver_headers(operator["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "lease_admin_headers": build_user_headers("test-lease-admin-1", "LeaseAdmin"),
    "settlement_clerk_headers": build_user_headers("test-settlement-clerk-1", "SettlementClerk"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "maintenance_coordinator_headers": build_user_headers("test-maintenance-coordinator-1", "MaintenanceCoordinator"),
    # Driver (entity-backed) — fallback for non-ownership tests only.
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def make_driver_headers(user_id: str) -> dict:
    """For Driver (entity-backed: OwnerOperator). Pass the actual
    OwnerOperator.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Driver")
