"""Pre-built role headers for every role in the PRD.

All roles are identity=opaque per PRD §2.1: X-User-ID is an opaque operator
identifier, never compared to any entity's id. A shared constant per role is
therefore safe for every call. Separate named constants are also provided for
the segregation-of-duties tests, where two operators of the SAME role must
carry DIFFERENT X-User-ID values.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "program_manager_headers": build_user_headers("test-program-manager-1", "ProgramManager"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "operations_analyst_headers": build_user_headers("test-operations-analyst-1", "OperationsAnalyst"),
    "finance_controller_headers": build_user_headers("test-finance-controller-1", "FinanceController"),
    "cardholder_ops_headers": build_user_headers("test-cardholder-ops-1", "CardholderOps"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_program_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For ComplianceOfficer. Pass distinct user_id values across the SoD
    boundary (submitter vs verifier/returner/rejecter)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_operations_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OperationsAnalyst")


def make_finance_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceController")


def make_cardholder_ops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CardholderOps")
