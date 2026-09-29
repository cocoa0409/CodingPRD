"""Pre-built role headers for every role named in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Operator identities. For the six operator roles the acting identifier is opaque
# and is never compared to any stored entity's id, so a shared constant is correct.
STRATEGIST_USER_ID = "u_strategist_1"
SECOND_STRATEGIST_USER_ID = "u_strategist_2"
APPROVER_USER_ID = "u_approver_1"
SECOND_APPROVER_USER_ID = "u_approver_2"
COMPLIANCE_USER_ID = "u_compliance_1"
HR_USER_ID = "u_hr_1"
REAL_ESTATE_USER_ID = "u_realestate_1"
OPS_ADMIN_USER_ID = "u_ops_1"

TEST_USERS = {
    "strategist_headers": build_user_headers(STRATEGIST_USER_ID, "NetworkStrategist"),
    "second_strategist_headers": build_user_headers(
        SECOND_STRATEGIST_USER_ID, "NetworkStrategist"
    ),
    "approver_headers": build_user_headers(APPROVER_USER_ID, "ConsolidationApprover"),
    "second_approver_headers": build_user_headers(
        SECOND_APPROVER_USER_ID, "ConsolidationApprover"
    ),
    "compliance_headers": build_user_headers(COMPLIANCE_USER_ID, "ComplianceOfficer"),
    "hr_headers": build_user_headers(HR_USER_ID, "HRPartner"),
    "real_estate_headers": build_user_headers(REAL_ESTATE_USER_ID, "RealEstateManager"),
    "ops_admin_headers": build_user_headers(OPS_ADMIN_USER_ID, "NetworkOpsAdmin"),
    # Fallback only for reads that carry no ownership restriction. Ownership-gated
    # calls must use make_branch_manager_headers(branch["id"]) instead.
    "branch_manager_headers": build_user_headers("u_branchmgr_1", "BranchManager"),
}


def make_branch_manager_headers(branch_id: str) -> dict:
    """Headers for the BranchManager role, whose acting identifier is the id of the
    acting branch. Pass the real Branch id whenever the call is ownership-gated."""
    return build_user_headers(branch_id, "BranchManager")


def make_strategist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "NetworkStrategist")


def make_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ConsolidationApprover")
