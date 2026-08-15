"""Pre-built role headers for every role in the PRD (§2.1).

Six roles use opaque operator identifiers: the server records X-User-ID on the
resources the operator touches (created_by_user_id, performed_by_user_id, ...)
but never compares it to an entity's id, so shared constants are canonical.
Distinct user ids within one role exist where segregation-of-duties compares
two operators (plan creator vs approver, collector vs analyst, preparer vs
signer).

The Employee role is entity-backed: X-User-ID must equal the acting Employee
record's id (e.g. when acknowledging a notification), so ownership-gated calls
MUST go through make_employee_headers(employee_id) with the real record id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "firm_admin_headers": build_user_headers("u_admin", "FirmAdmin"),
    "ih_headers": build_user_headers("u_ih_1", "IndustrialHygienist"),
    "ih2_headers": build_user_headers("u_ih_2", "IndustrialHygienist"),
    "cih_headers": build_user_headers("u_cih_1", "CIHDirector"),
    "cih2_headers": build_user_headers("u_cih_2", "CIHDirector"),
    "tech_headers": build_user_headers("u_tech_1", "FieldTechnician"),
    "tech2_headers": build_user_headers("u_tech_2", "FieldTechnician"),
    "lab_headers": build_user_headers("u_lab_1", "LabAnalyst"),
    "lab2_headers": build_user_headers("u_lab_2", "LabAnalyst"),
    "ssm_headers": build_user_headers("u_ssm_1", "SiteSafetyManager"),
    # Fallback only for calls that are not ownership-gated.
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
}


def make_firm_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FirmAdmin")


def make_ih_headers(user_id: str) -> dict:
    """IndustrialHygienist with a specific operator id (SoD scenarios)."""
    return build_user_headers(user_id, "IndustrialHygienist")


def make_cih_headers(user_id: str) -> dict:
    """CIHDirector with a specific operator id (SoD scenarios)."""
    return build_user_headers(user_id, "CIHDirector")


def make_tech_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FieldTechnician")


def make_lab_headers(user_id: str) -> dict:
    """LabAnalyst with a specific operator id (chain-of-custody scenarios)."""
    return build_user_headers(user_id, "LabAnalyst")


def make_ssm_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SiteSafetyManager")


def make_employee_headers(user_id: str) -> dict:
    """Employee is entity-backed: pass the actual Employee.id as user_id
    whenever the call is ownership-gated (notification acknowledge)."""
    return build_user_headers(user_id, "Employee")
