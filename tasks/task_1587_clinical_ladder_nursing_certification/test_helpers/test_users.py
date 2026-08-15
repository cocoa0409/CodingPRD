"""Pre-built role headers for every role in the PRD (§2.1).

Nurse is an entity-backed role: when the call is ownership-gated the headers
MUST carry the acting Nurse record's id — use make_nurse_headers(nurse_id).
The shared nurse constant is a fallback for non-ownership tests only.
ProgramAdmin / PayrollOfficer / RetentionAnalyst carry opaque operator ids.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Entity-backed role — fallback for non-ownership tests only.
    "nurse_headers": build_user_headers("test-nurse-1", "Nurse"),
    # Opaque roles — canonical form.
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "payroll_officer_headers": build_user_headers("test-payroll-1", "PayrollOfficer"),
    "retention_analyst_headers": build_user_headers("test-analyst-1", "RetentionAnalyst"),
}


def make_nurse_headers(user_id: str) -> dict:
    """For Nurse (entity-backed). Pass the actual Nurse.id as user_id
    whenever the call is ownership-gated (submit, withdraw, score, recuse,
    participation-event creation, claim creation)."""
    return build_user_headers(user_id, "Nurse")


def make_program_admin_headers(user_id: str) -> dict:
    """ProgramAdmin with a specific opaque operator id — used to exercise
    segregation-of-duties checks that compare the operator id against
    entity-backed reviewer/claimant ids."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_payroll_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PayrollOfficer")


def make_retention_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RetentionAnalyst")
