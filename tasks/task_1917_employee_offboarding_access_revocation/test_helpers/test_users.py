"""Pre-built role headers for every role in the PRD.

All eleven roles have identity "opaque" — X-User-ID is a string identifier the
server records on certain resources for segregation-of-duties comparison, but
it is never compared to any entity's id. So per-instance builders are not
required; shared constants are canonical for every role. Distinct user ids are
still needed wherever a SoD rule compares actor id vs. recorded counterparty
id, so fixtures below hand out named constants for the common counterparts.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants (one per role). Safe for any opaque-role call.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "hr_partner_headers": build_user_headers("hr-intake-1", "HRPartner"),
    "hr_partner_approver_headers": build_user_headers("hr-approver-1", "HRPartner"),
    "hr_reviewer_headers": build_user_headers("hr-reviewer-1", "HRReviewer"),
    "hr_director_headers": build_user_headers("hr-director-1", "HRDirector"),
    "payroll_headers": build_user_headers("payroll-calc-1", "PayrollSpecialist"),
    "payroll_approver_headers": build_user_headers("payroll-approver-1", "PayrollSpecialist"),
    "it_operator_headers": build_user_headers("it-op-1", "ITOperator"),
    "it_verifier_headers": build_user_headers("it-ver-1", "ITVerifier"),
    "it_manager_headers": build_user_headers("it-mgr-1", "ITManager"),
    "manager_headers": build_user_headers("mgr-1", "Manager"),
    "asset_clerk_headers": build_user_headers("asset-clerk-1", "AssetClerk"),
    "benefits_admin_headers": build_user_headers("ben-admin-1", "BenefitsAdministrator"),
}
