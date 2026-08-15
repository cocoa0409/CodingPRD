"""Pre-built role headers for every role in the PRD.

PRD §2.1: all six roles use opaque operator identities — the server never
compares X-User-ID against any resource's id. The single exception is the
segregation-of-duties machinery on suspect investigations: quarantine stamps
quarantined_by_user_id with the caller's X-User-ID, and clear/confirm compare
the new caller's header against the stored value (PRD §3.6). Tests exercising
segregation of duties therefore need per-user QualityAssuranceLead headers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "order_manager_headers": build_user_headers("om-default", "OrderManager"),
    "compliance_officer_headers": build_user_headers("co-default", "ComplianceOfficer"),
    "warehouse_operator_headers": build_user_headers("wh-default", "WarehouseOperator"),
    "qa_lead_headers": build_user_headers("qa-default", "QualityAssuranceLead"),
    "billing_clerk_headers": build_user_headers("bc-default", "BillingClerk"),
    "contract_admin_headers": build_user_headers("ca-default", "ContractAdministrator"),
}


def make_qa_lead_headers(user_id: str) -> dict:
    """Per-user QualityAssuranceLead headers. Required for segregation-of-duties
    scenarios: quarantine stamps the caller's X-User-ID, and clear/confirm must
    come from a different user."""
    return build_user_headers(user_id, "QualityAssuranceLead")
