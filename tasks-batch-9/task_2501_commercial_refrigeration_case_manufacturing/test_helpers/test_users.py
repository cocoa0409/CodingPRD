"""Pre-built request headers for every role named in PRD §2.1.

Eight of the nine roles carry an opaque operator identifier that the server
never compares against any entity's `id` (PRD §2.1), so a shared constant is
the canonical form for them.

`InstallContractor` is the single exception: `X-User-ID` is the `id` of the
acting install crew, so ownership-gated calls MUST use
``make_install_contractor_headers(crew_id)`` with the real crew id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# User ids used throughout the suite. Two SalesEngineer ids and two
# ComplianceOfficer ids exist because PRD §2.9 splits pricing from approval and
# submission from label issuance across two different people.
PLATFORM_ADMIN_USER_ID = "admin-001"
DESIGN_ENGINEER_USER_ID = "eng-001"
DESIGN_ENGINEER_ALT_USER_ID = "eng-002"
TEST_LAB_TECHNICIAN_USER_ID = "lab-001"
COMPLIANCE_OFFICER_USER_ID = "co-001"
COMPLIANCE_OFFICER_ALT_USER_ID = "co-002"
SALES_ENGINEER_USER_ID = "sales-001"
SALES_ENGINEER_ALT_USER_ID = "sales-002"
PLANT_SUPERVISOR_USER_ID = "plant-001"
LOGISTICS_COORDINATOR_USER_ID = "log-001"
SERVICE_MANAGER_USER_ID = "svc-001"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ID, "PlatformAdmin"
    ),
    "design_engineer_headers": build_user_headers(
        DESIGN_ENGINEER_USER_ID, "DesignEngineer"
    ),
    "design_engineer_alt_headers": build_user_headers(
        DESIGN_ENGINEER_ALT_USER_ID, "DesignEngineer"
    ),
    "test_lab_technician_headers": build_user_headers(
        TEST_LAB_TECHNICIAN_USER_ID, "TestLabTechnician"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    "compliance_officer_alt_headers": build_user_headers(
        COMPLIANCE_OFFICER_ALT_USER_ID, "ComplianceOfficer"
    ),
    "sales_engineer_headers": build_user_headers(
        SALES_ENGINEER_USER_ID, "SalesEngineer"
    ),
    "sales_engineer_alt_headers": build_user_headers(
        SALES_ENGINEER_ALT_USER_ID, "SalesEngineer"
    ),
    "plant_supervisor_headers": build_user_headers(
        PLANT_SUPERVISOR_USER_ID, "PlantSupervisor"
    ),
    "logistics_coordinator_headers": build_user_headers(
        LOGISTICS_COORDINATOR_USER_ID, "LogisticsCoordinator"
    ),
    "service_manager_headers": build_user_headers(
        SERVICE_MANAGER_USER_ID, "ServiceManager"
    ),
    # Fallback only for tests that never exercise crew ownership.
    "install_contractor_headers": build_user_headers(
        "crew-placeholder", "InstallContractor"
    ),
}


def make_install_contractor_headers(crew_id: str) -> Dict[str, str]:
    """Headers for an `InstallContractor` acting as a specific install crew.

    PRD §2.1: when `X-User-Role` is `InstallContractor`, `X-User-ID` is the `id`
    of the acting install crew, so `crew_id` must be a real InstallCrew id.
    """
    return build_user_headers(crew_id, "InstallContractor")


def make_platform_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "PlatformAdmin")


def make_design_engineer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "DesignEngineer")


def make_test_lab_technician_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "TestLabTechnician")


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_sales_engineer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "SalesEngineer")


def make_plant_supervisor_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "PlantSupervisor")


def make_logistics_coordinator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "LogisticsCoordinator")


def make_service_manager_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ServiceManager")


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying `X-User-Role` but no `X-User-ID` at all (PRD §2.1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
