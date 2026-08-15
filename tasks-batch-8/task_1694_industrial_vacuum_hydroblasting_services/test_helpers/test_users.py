"""Pre-built role headers for every role in the PRD.

All seven roles are opaque (X-User-ID is an operator identifier never compared
to a resource id), so shared constants are the canonical form. Per-user builders
exist for segregation-of-duties tests that must control the exact X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("pa_1", "PlatformAdmin"),
    "account_manager_headers": build_user_headers("am_1", "AccountManager"),
    "project_manager_headers": build_user_headers("pm_1", "ProjectManager"),
    "field_supervisor_headers": build_user_headers("fs_1", "FieldSupervisor"),
    "safety_manager_headers": build_user_headers("sm_1", "SafetyManager"),
    "compliance_officer_headers": build_user_headers("co_1", "ComplianceOfficer"),
    "environmental_approver_headers": build_user_headers("ea_1", "EnvironmentalApprover"),
}


def make_platform_admin_headers(user_id: str = "pa_1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_account_manager_headers(user_id: str = "am_1") -> dict:
    return build_user_headers(user_id, "AccountManager")


def make_project_manager_headers(user_id: str = "pm_1") -> dict:
    return build_user_headers(user_id, "ProjectManager")


def make_field_supervisor_headers(user_id: str = "fs_1") -> dict:
    """FieldSupervisor headers pinned to a specific X-User-ID (SoD-sensitive)."""
    return build_user_headers(user_id, "FieldSupervisor")


def make_safety_manager_headers(user_id: str = "sm_1") -> dict:
    """SafetyManager headers pinned to a specific X-User-ID (SoD-sensitive)."""
    return build_user_headers(user_id, "SafetyManager")


def make_compliance_officer_headers(user_id: str = "co_1") -> dict:
    """ComplianceOfficer headers pinned to a specific X-User-ID (SoD-sensitive)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_environmental_approver_headers(user_id: str = "ea_1") -> dict:
    """EnvironmentalApprover headers pinned to a specific X-User-ID (SoD)."""
    return build_user_headers(user_id, "EnvironmentalApprover")
