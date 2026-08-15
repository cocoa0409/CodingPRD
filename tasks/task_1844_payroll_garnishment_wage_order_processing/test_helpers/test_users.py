"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are opaque: no role ties X-User-ID to a persisted entity, so the
shared constants below are the canonical form. Distinct user IDs per role keep
the segregation-of-duties comparison (PRD §2.10) satisfied: the specialist who
pays a run never shares an X-User-ID with the manager who confirms it.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("user-admin-1", "employer_payroll_admin"),
    "specialist_headers": build_user_headers("user-specialist-1", "payroll_specialist"),
    "manager_headers": build_user_headers("user-manager-1", "payroll_manager"),
    "auditor_headers": build_user_headers("user-auditor-1", "compliance_auditor"),
}
