"""Pre-built role headers for every role named in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Five of the six roles carry an opaque identity, so a shared
# constant is the canonical form for them. DepartmentManager is backed by the
# Department entity's manager_user_id, so the shared constant below is only safe
# for tests that never exercise a department-ownership check.
TEST_USERS = {
    "admin_headers": build_user_headers("user-admin-1", "SystemAdmin"),
    "analyst_headers": build_user_headers("user-analyst-1", "RevenueIntegrityAnalyst"),
    "analyst2_headers": build_user_headers("user-analyst-2", "RevenueIntegrityAnalyst"),
    "approver_headers": build_user_headers("user-approver-1", "PricingCommitteeApprover"),
    "approver2_headers": build_user_headers("user-approver-2", "PricingCommitteeApprover"),
    "compliance_headers": build_user_headers("user-compliance-1", "ComplianceOfficer"),
    "contract_headers": build_user_headers("user-contract-1", "ContractManager"),
    "manager_headers": build_user_headers("user-manager-1", "DepartmentManager"),
}

# Canonical opaque operator identifiers, so tests can assert audit-trail fields.
ADMIN_USER_ID = "user-admin-1"
ANALYST_USER_ID = "user-analyst-1"
ANALYST2_USER_ID = "user-analyst-2"
APPROVER_USER_ID = "user-approver-1"
APPROVER2_USER_ID = "user-approver-2"
COMPLIANCE_USER_ID = "user-compliance-1"
CONTRACT_USER_ID = "user-contract-1"

# Department manager identifiers used when standing up departments. These are the
# values written to Department.manager_user_id, and the same values must be sent
# as X-User-ID on every department-scoped call.
MANAGER_USER_ID = "user-manager-1"
MANAGER2_USER_ID = "user-manager-2"


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RevenueIntegrityAnalyst")


def make_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PricingCommitteeApprover")


def make_compliance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_contract_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractManager")


def make_manager_headers(user_id: str) -> dict:
    """For DepartmentManager. Pass the department's manager_user_id as user_id
    whenever the call is department-scoped."""
    return build_user_headers(user_id, "DepartmentManager")


ALL_ROLE_HEADERS = {
    "SystemAdmin": TEST_USERS["admin_headers"],
    "RevenueIntegrityAnalyst": TEST_USERS["analyst_headers"],
    "PricingCommitteeApprover": TEST_USERS["approver_headers"],
    "ComplianceOfficer": TEST_USERS["compliance_headers"],
    "ContractManager": TEST_USERS["contract_headers"],
    "DepartmentManager": TEST_USERS["manager_headers"],
}
