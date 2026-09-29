"""Pre-built role headers for the five roles named in PRD Section 2.1.

PRD 2.1: when `X-User-Role` is `AcquirerOps`, `X-User-ID` is the `id` of the
acting `Acquirer`, so any ownership-gated AcquirerOps call MUST be made with
`make_acquirer_ops_headers(<the real Acquirer.id>)`. For the other four roles
`X-User-ID` is an opaque operator identifier not tied to any persisted entity,
so the shared constants below are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used across the suite.
NETWORK_ADMIN_USER_ID = "admin-1"
CATEGORY_ANALYST_USER_ID = "analyst-7"
SECOND_CATEGORY_ANALYST_USER_ID = "CAN-1"
CATEGORY_APPROVER_USER_ID = "approver-9"
SECOND_CATEGORY_APPROVER_USER_ID = "approver-4"
COMPLIANCE_AUDITOR_USER_ID = "auditor-1"
SECOND_COMPLIANCE_AUDITOR_USER_ID = "CA-2"

TEST_USERS = {
    "network_admin_headers": build_user_headers(NETWORK_ADMIN_USER_ID, "NetworkAdmin"),
    # AcquirerOps is entity-backed: this shared constant is only safe for calls
    # that fail before the ownership comparison (bad payload, unknown id).
    "acquirer_ops_headers": build_user_headers("unbound-acquirer", "AcquirerOps"),
    "category_analyst_headers": build_user_headers(
        CATEGORY_ANALYST_USER_ID, "CategoryAnalyst"
    ),
    "second_category_analyst_headers": build_user_headers(
        SECOND_CATEGORY_ANALYST_USER_ID, "CategoryAnalyst"
    ),
    "category_approver_headers": build_user_headers(
        CATEGORY_APPROVER_USER_ID, "CategoryApprover"
    ),
    "compliance_auditor_headers": build_user_headers(
        COMPLIANCE_AUDITOR_USER_ID, "ComplianceAuditor"
    ),
    "second_compliance_auditor_headers": build_user_headers(
        SECOND_COMPLIANCE_AUDITOR_USER_ID, "ComplianceAuditor"
    ),
}


def make_acquirer_ops_headers(acquirer_id: str) -> dict:
    """Headers for AcquirerOps. Pass the real `Acquirer.id` — PRD 2.1 compares
    the resource's acquirer foreign-key field to `X-User-ID`."""
    return build_user_headers(acquirer_id, "AcquirerOps")


def make_network_admin_headers(user_id: str = NETWORK_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "NetworkAdmin")


def make_category_analyst_headers(user_id: str = CATEGORY_ANALYST_USER_ID) -> dict:
    return build_user_headers(user_id, "CategoryAnalyst")


def make_category_approver_headers(user_id: str = CATEGORY_APPROVER_USER_ID) -> dict:
    return build_user_headers(user_id, "CategoryApprover")


def make_compliance_auditor_headers(user_id: str = COMPLIANCE_AUDITOR_USER_ID) -> dict:
    return build_user_headers(user_id, "ComplianceAuditor")


def headers_without_role(user_id: str = NETWORK_ADMIN_USER_ID) -> dict:
    """Headers carrying `X-User-ID` but no `X-User-Role` — PRD 2.1 refuses this
    with `ERR_UNAUTHENTICATED`."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
