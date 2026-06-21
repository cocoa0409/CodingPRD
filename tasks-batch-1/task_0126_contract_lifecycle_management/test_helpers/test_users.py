"""Pre-built role headers for every role in the Contract Lifecycle Management API.

All six roles use an opaque identity model (PRD §2.1): X-User-ID is an operator
identifier never compared to any persisted entity's id. It IS recorded where an
accountable actor is required (drafter_user_id, authored_by_user_id,
approver_user_id, decided_by_user_id) and those recorded strings drive the
segregation-of-duties checks. Tests therefore control the X-User-ID string
explicitly via build_user_headers / the headers_for helper below whenever a
segregation-of-duties relationship matters.
"""
from prd_bench_local_runner.testing import build_user_headers

# Distinct default operator identities per role. These cover the common case
# where the drafter (a ContractManager) and the approver / risk officer are
# DIFFERENT seats, satisfying segregation of duties by default.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "clause_librarian_headers": build_user_headers("librarian-1", "ClauseLibrarian"),
    "contract_manager_headers": build_user_headers("mgr-1", "ContractManager"),
    "contract_approver_headers": build_user_headers("appr-1", "ContractApprover"),
    "risk_officer_headers": build_user_headers("risk-1", "RiskOfficer"),
    "signer_headers": build_user_headers("signer-1", "Signer"),
}


def headers_for(role: str, user_id: str) -> dict:
    """Build auth headers for an arbitrary (role, X-User-ID) pair.

    Used wherever a test must pin the acting operator's id — e.g. to make a
    ContractApprover whose X-User-ID equals the contract's drafter (to trigger
    ERR_SELF_APPROVAL), or to keep the approver distinct from the drafter."""
    return build_user_headers(user_id, role)
