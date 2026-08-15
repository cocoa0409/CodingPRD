"""Pre-built role headers for every role in the PRD (§2.1).

OperatorAdmin, SiteManager, MaintenanceLead, ComplianceInspector, and
IntakeCoordinator are opaque identities: X-User-ID is not tied to any persisted
entity. Resident is entity-backed by Household: X-User-ID IS the acting
Household's id, so ownership-gated calls MUST use make_resident_headers with
the real household id. The shared resident constant exists only for tests that
do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "operator_admin_headers": build_user_headers("test-admin-1", "OperatorAdmin"),
    "site_manager_headers": build_user_headers("test-sm-1", "SiteManager"),
    "maintenance_lead_headers": build_user_headers("test-ml-1", "MaintenanceLead"),
    "compliance_inspector_headers": build_user_headers("test-ci-1", "ComplianceInspector"),
    "intake_coordinator_headers": build_user_headers("test-ic-1", "IntakeCoordinator"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
}


def make_operator_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "OperatorAdmin")


def make_site_manager_headers(user_id: str = "test-sm-1") -> dict:
    return build_user_headers(user_id, "SiteManager")


def make_maintenance_lead_headers(user_id: str = "test-ml-1") -> dict:
    return build_user_headers(user_id, "MaintenanceLead")


def make_compliance_inspector_headers(user_id: str = "test-ci-1") -> dict:
    return build_user_headers(user_id, "ComplianceInspector")


def make_intake_coordinator_headers(user_id: str = "test-ic-1") -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_resident_headers(household_id: str) -> dict:
    """For Resident (entity_backed:Household). Pass the acting Household.id
    whenever the call is ownership-gated (complaint filing, giving notice)."""
    return build_user_headers(household_id, "Resident")
