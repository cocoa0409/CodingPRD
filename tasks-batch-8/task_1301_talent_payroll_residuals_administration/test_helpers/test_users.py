"""Pre-built role headers for every role in the PRD (§2.1).

All five roles are opaque operator identifiers: X-User-ID is recorded where
relevant (e.g. PayBatch.created_by_user_id, GrievanceCase.filed_by_user_id)
but never compared to any entity id. The fixed user ids below matter only
where segregation of duties compares the batch approver's X-User-ID against
created_by_user_id: the shared clerk ("clerk-1") and supervisor ("sup-1")
differ, so the standard batch flow passes the SoD gate.
"""
from prd_bench_local_runner.testing import build_user_headers

CLERK_USER_ID = "clerk-1"
SUPERVISOR_USER_ID = "sup-1"
AUDITOR_USER_ID = "aud-1"
ADMIN_USER_ID = "admin-1"
ACCOUNTANT_USER_ID = "acct-1"

TEST_USERS = {
    "payroll_admin_headers": build_user_headers(ADMIN_USER_ID, "PayrollAdmin"),
    "production_accountant_headers": build_user_headers(ACCOUNTANT_USER_ID, "ProductionAccountant"),
    "payroll_clerk_headers": build_user_headers(CLERK_USER_ID, "PayrollClerk"),
    "payroll_supervisor_headers": build_user_headers(SUPERVISOR_USER_ID, "PayrollSupervisor"),
    "union_auditor_headers": build_user_headers(AUDITOR_USER_ID, "UnionAuditor"),
}


def make_payroll_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PayrollAdmin")


def make_production_accountant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionAccountant")


def make_payroll_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PayrollClerk")


def make_payroll_supervisor_headers(user_id: str) -> dict:
    """Segregation of duties: pass the batch creator's user id here to
    exercise the ERR_SEGREGATION_OF_DUTIES path on batch approve."""
    return build_user_headers(user_id, "PayrollSupervisor")


def make_union_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "UnionAuditor")
