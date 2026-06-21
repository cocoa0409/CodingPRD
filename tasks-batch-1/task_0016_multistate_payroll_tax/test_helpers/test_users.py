"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use `identity: opaque` per the PRD: `X-User-ID` is an opaque operator
identifier never compared to any persisted entity's `id`. Ownership in this domain
is enforced by segregation-of-duties checks against `prepared_by_user_id` /
`approved_by_user_id` on PaycheckRun, not by entity-backed identity. Therefore:
all roles use shared TEST_USERS constants. SoD tests build distinct operator
ids explicitly with `build_user_headers(...)` to control U_PREP / U_APPR identity.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "hr_clerk_headers": build_user_headers("test-hrclerk-1", "HRClerk"),
    "payroll_preparer_headers": build_user_headers("U_PREP", "PayrollPreparer"),
    "payroll_approver_headers": build_user_headers("U_APPR", "PayrollApprover"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_preparer_headers(user_id: str) -> dict:
    """Build a PayrollPreparer header tied to a specific operator id.
    Useful to control `prepared_by_user_id` for segregation-of-duties tests."""
    return build_user_headers(user_id, "PayrollPreparer")


def make_approver_headers(user_id: str) -> dict:
    """Build a PayrollApprover header tied to a specific operator id.
    Useful to assert that approver != preparer for SoD."""
    return build_user_headers(user_id, "PayrollApprover")
