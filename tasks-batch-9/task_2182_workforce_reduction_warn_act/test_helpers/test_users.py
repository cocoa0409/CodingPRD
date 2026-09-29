"""Pre-built role headers for every role the PRD recognises."""

from prd_bench_local_runner.testing import build_user_headers

# Four of the five roles carry an opaque operator identifier that the server
# never compares to any persisted entity id, so a shared constant is correct
# for them.  SeparatingEmployee is different: its X-User-ID must be the acting
# Employee's own id, so tests build those headers per instance.
TEST_USERS = {
    "lead_headers": build_user_headers("u-lead-1", "RestructuringLead"),
    "lead_2_headers": build_user_headers("u-lead-2", "RestructuringLead"),
    "counsel_headers": build_user_headers("u-counsel-1", "EmploymentCounsel"),
    "counsel_2_headers": build_user_headers("u-counsel-2", "EmploymentCounsel"),
    "benefits_headers": build_user_headers("u-benefits-1", "BenefitsAdministrator"),
    "admin_headers": build_user_headers("u-admin-1", "SystemAdmin"),
    # Fallback only for calls that never exercise offer ownership.
    "employee_headers": build_user_headers(
        "u-employee-unknown", "SeparatingEmployee"
    ),
}

USER_IDS = {
    "LEAD": "u-lead-1",
    "LEAD_2": "u-lead-2",
    "COUNSEL": "u-counsel-1",
    "COUNSEL_2": "u-counsel-2",
    "BENEFITS": "u-benefits-1",
    "ADMIN": "u-admin-1",
}


def make_lead_headers(user_id: str) -> dict:
    """RestructuringLead acting under an explicit operator id."""
    return build_user_headers(user_id, "RestructuringLead")


def make_counsel_headers(user_id: str) -> dict:
    """EmploymentCounsel acting under an explicit operator id."""
    return build_user_headers(user_id, "EmploymentCounsel")


def make_benefits_headers(user_id: str) -> dict:
    """BenefitsAdministrator acting under an explicit operator id."""
    return build_user_headers(user_id, "BenefitsAdministrator")


def make_admin_headers(user_id: str) -> dict:
    """SystemAdmin acting under an explicit operator id."""
    return build_user_headers(user_id, "SystemAdmin")


def make_separating_employee_headers(employee_id: str) -> dict:
    """SeparatingEmployee: X-User-ID must be the acting Employee's own id, which
    the server compares to the offer's Selection.employee_id."""
    return build_user_headers(employee_id, "SeparatingEmployee")
