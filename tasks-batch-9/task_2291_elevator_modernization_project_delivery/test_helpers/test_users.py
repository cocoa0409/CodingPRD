"""Pre-built role headers for every role named by the PRD.

Both `X-User-ID` and `X-User-Role` are required on every request. For the
building representative the `X-User-ID` must be the id of the modernization
project they represent; for the AHJ inspector it must be the id of the
jurisdiction they inspect for. Those two roles therefore always go through
the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the four roles whose identity is not tied to a
# stored row, and for calls that never reach an ownership check.
TEST_USERS = {
    "project_manager_headers": build_user_headers("pm-001", "ProjectManager"),
    "survey_technician_headers": build_user_headers("tech-001", "SurveyTechnician"),
    "service_manager_headers": build_user_headers("svc-001", "ServiceManager"),
    "system_operator_headers": build_user_headers("ops-001", "SystemOperator"),
    # The two entity-backed roles: these constants are only for calls that are
    # rejected before any scope check runs (missing role, unknown path id).
    "building_representative_headers": build_user_headers(
        "rep-unowned", "BuildingRepresentative"
    ),
    "ahj_inspector_headers": build_user_headers("ahj-unowned", "AHJInspector"),
}


def make_project_manager_headers(user_id: str) -> dict:
    """Headers for a specific ProjectManager identity."""
    return build_user_headers(user_id, "ProjectManager")


def make_survey_technician_headers(user_id: str) -> dict:
    """Headers for a specific SurveyTechnician identity.

    The countersigning caller's X-User-ID must differ from the survey's
    surveyed_by_user_id, so submit and countersign use distinct ids.
    """
    return build_user_headers(user_id, "SurveyTechnician")


def make_building_representative_headers(project_id: str) -> dict:
    """Headers for a BuildingRepresentative. Pass the ModernizationProject id."""
    return build_user_headers(project_id, "BuildingRepresentative")


def make_ahj_inspector_headers(jurisdiction_id: str) -> dict:
    """Headers for an AHJInspector. Pass the Jurisdiction id."""
    return build_user_headers(jurisdiction_id, "AHJInspector")


def make_service_manager_headers(user_id: str) -> dict:
    """Headers for a specific ServiceManager identity."""
    return build_user_headers(user_id, "ServiceManager")


def make_system_operator_headers(user_id: str) -> dict:
    """Headers for a specific SystemOperator identity."""
    return build_user_headers(user_id, "SystemOperator")


PROJECT_MANAGER = TEST_USERS["project_manager_headers"]
SURVEY_TECHNICIAN = TEST_USERS["survey_technician_headers"]
SERVICE_MANAGER = TEST_USERS["service_manager_headers"]
SYSTEM_OPERATOR = TEST_USERS["system_operator_headers"]
