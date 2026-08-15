"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants are safe for opaque roles and for tests that do not exercise
ownership. The Employee role is entity-backed: for ownership-gated calls,
build headers with make_employee_headers(employee["id"]) so X-User-ID equals
the real Employee id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "tax_director_headers": build_user_headers("dir-1", "TaxDirector"),
    "nexus_analyst_headers": build_user_headers("na-1", "NexusAnalyst"),
    "ui_specialist_headers": build_user_headers("uis-1", "UISpecialist"),
    "payroll_compliance_lead_headers": build_user_headers("pcl-1", "PayrollComplianceLead"),
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
    # Fallback only for Employee-role tests that do not exercise ownership.
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
}


def make_tax_director_headers(user_id: str) -> dict:
    """TaxDirector headers with a specific opaque operator id (SoD-sensitive)."""
    return build_user_headers(user_id, "TaxDirector")


def make_nexus_analyst_headers(user_id: str) -> dict:
    """NexusAnalyst headers with a specific opaque operator id (SoD-sensitive)."""
    return build_user_headers(user_id, "NexusAnalyst")


def make_ui_specialist_headers(user_id: str) -> dict:
    """UISpecialist headers with a specific opaque operator id (SoD-sensitive)."""
    return build_user_headers(user_id, "UISpecialist")


def make_payroll_compliance_lead_headers(user_id: str) -> dict:
    """PayrollComplianceLead headers with a specific operator id (SoD-sensitive)."""
    return build_user_headers(user_id, "PayrollComplianceLead")


def make_employee_headers(employee_id: str) -> dict:
    """Employee is entity-backed: pass the actual Employee.id whenever the call
    is ownership-gated (election create/revoke, location-change create/cancel)."""
    return build_user_headers(employee_id, "Employee")
