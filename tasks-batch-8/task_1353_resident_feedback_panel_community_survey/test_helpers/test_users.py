"""Pre-built role headers for every role in the PRD.

All six roles use opaque operator identities (PRD §2.1): X-User-ID is never
compared against any entity's id. The single exception is DepartmentLiaison,
whose X-User-ID carries the department name itself and is compared against a
commitment's department_name — use make_liaison_headers(department_name) for
department-scoped commitment actions.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "panel_manager": build_user_headers("pm-1", "PanelManager"),
    "survey_designer": build_user_headers("sd-1", "SurveyDesigner"),
    "data_analyst": build_user_headers("analyst-1", "DataAnalyst"),
    "incentive_clerk": build_user_headers("clerk-1", "IncentiveClerk"),
    "privacy_officer": build_user_headers("privacy-1", "PrivacyOfficer"),
    "department_liaison": build_user_headers("DEPT_TRANSPORT", "DepartmentLiaison"),
}


def make_panel_manager_headers(user_id: str = "pm-1") -> dict:
    return build_user_headers(user_id, "PanelManager")


def make_designer_headers(user_id: str = "sd-1") -> dict:
    return build_user_headers(user_id, "SurveyDesigner")


def make_analyst_headers(user_id: str = "analyst-1") -> dict:
    """DataAnalyst identity is recorded as finalized_by_user_id on finalize;
    choose a distinct id when segregation-of-duties matters."""
    return build_user_headers(user_id, "DataAnalyst")


def make_clerk_headers(user_id: str = "clerk-1") -> dict:
    return build_user_headers(user_id, "IncentiveClerk")


def make_privacy_headers(user_id: str = "privacy-1") -> dict:
    """PrivacyOfficer identity must differ from the snapshot finalizer's
    X-User-ID for a publish to pass the segregation-of-duties check."""
    return build_user_headers(user_id, "PrivacyOfficer")


def make_liaison_headers(department_name: str) -> dict:
    """DepartmentLiaison: X-User-ID IS the department name; commitment actions
    require commitment.department_name == X-User-ID."""
    return build_user_headers(department_name, "DepartmentLiaison")
