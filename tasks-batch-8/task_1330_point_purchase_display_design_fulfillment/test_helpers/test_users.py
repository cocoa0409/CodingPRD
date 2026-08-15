"""Pre-built role headers for every role in the PRD (§2.1).

All nine roles are opaque: X-User-ID is an operator identifier that is never
compared against any persisted entity's id, so the shared constants below are
the canonical form for every call. The make_*_headers builders exist only for
tests that want to pin a specific X-User-ID string.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "program_manager_headers": build_user_headers("test-program-manager-1", "ProgramManager"),
    "designer_headers": build_user_headers("test-designer-1", "Designer"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "production_planner_headers": build_user_headers("test-production-planner-1", "ProductionPlanner"),
    "warehouse_operator_headers": build_user_headers("test-warehouse-operator-1", "WarehouseOperator"),
    "logistics_coordinator_headers": build_user_headers("test-logistics-coordinator-1", "LogisticsCoordinator"),
    "claims_adjuster_headers": build_user_headers("test-claims-adjuster-1", "ClaimsAdjuster"),
    "field_service_manager_headers": build_user_headers("test-field-service-manager-1", "FieldServiceManager"),
}

# Short aliases used throughout fixtures and tests.
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
PROGRAM_MANAGER = TEST_USERS["program_manager_headers"]
DESIGNER = TEST_USERS["designer_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]
PRODUCTION_PLANNER = TEST_USERS["production_planner_headers"]
WAREHOUSE_OPERATOR = TEST_USERS["warehouse_operator_headers"]
LOGISTICS_COORDINATOR = TEST_USERS["logistics_coordinator_headers"]
CLAIMS_ADJUSTER = TEST_USERS["claims_adjuster_headers"]
FIELD_SERVICE_MANAGER = TEST_USERS["field_service_manager_headers"]


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_program_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramManager")


def make_designer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Designer")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_production_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_warehouse_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarehouseOperator")


def make_logistics_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LogisticsCoordinator")


def make_claims_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_field_service_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FieldServiceManager")
