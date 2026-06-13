"""Pre-built role headers for every role in the Auto Title Loan PRD.

All six roles use an opaque user identity: X-User-ID is never compared to any
entity id for ownership. The shared TEST_USERS constants are therefore the
canonical form for every role.

The one place X-User-ID carries meaning beyond authorization is segregation of
duties on application approval: the approving Underwriter's X-User-ID must differ
from the X-User-ID of the Appraiser who finalized the appraisal. The make_*_headers
builders let tests pin a specific X-User-ID so that segregation can be exercised
(distinct ids) or deliberately collided (same id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles. Each role's default user id is
# distinct from every other role's, which keeps segregation-of-duties satisfied by
# default when an Appraiser finalizes and a different-role/different-id user acts.
TEST_USERS = {
    "compliance_admin_headers": build_user_headers("compliance-admin-1", "ComplianceAdmin"),
    "appraiser_headers": build_user_headers("appraiser-1", "Appraiser"),
    "underwriter_headers": build_user_headers("underwriter-1", "Underwriter"),
    "loan_servicer_headers": build_user_headers("loan-servicer-1", "LoanServicer"),
    "recovery_manager_headers": build_user_headers("recovery-manager-1", "RecoveryManager"),
    "title_clerk_headers": build_user_headers("title-clerk-1", "TitleClerk"),
}


def make_compliance_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceAdmin")


def make_appraiser_headers(user_id: str) -> dict:
    """Pin the Appraiser's X-User-ID (retained per appraisal for segregation of duties)."""
    return build_user_headers(user_id, "Appraiser")


def make_underwriter_headers(user_id: str) -> dict:
    """Pin the approving Underwriter's X-User-ID (checked against the appraisal's finalizer)."""
    return build_user_headers(user_id, "Underwriter")


def make_loan_servicer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LoanServicer")


def make_recovery_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RecoveryManager")


def make_title_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TitleClerk")
