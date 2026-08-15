"""Pre-built role headers for the six PRD roles (PRD §2.1).

Per PRD §2.1, every role's X-User-ID is an opaque operator identifier — the server
never compares it to any entity's id — so shared constants are canonical for all
roles. Two distinct users exist for ComplianceOfficer and Auditor so that the
segregation-of-duties rules (PRD §2.9) can be exercised: uploader vs reviewer,
campaign opener vs closer, remediation assignee vs resolver.
"""
from prd_bench_local_runner.testing import build_user_headers

# Well-known operator ids — referenced by name in remediation payloads
# (assigned_to_user_id) and segregation-of-duties assertions.
USER_IDS = {
    "TENANT_ADMIN": "u_admin",
    "COMPLIANCE_OFFICER": "u_co1",
    "COMPLIANCE_OFFICER_2": "u_co2",
    "AUDITOR": "u_aud1",
    "AUDITOR_2": "u_aud2",
    "ORDER_CLERK": "u_oc1",
    "FULFILLMENT_CLERK": "u_ff1",
    "BILLING_CLERK": "u_bc1",
}

TEST_USERS = {
    "tenant_admin_headers": build_user_headers(USER_IDS["TENANT_ADMIN"], "TenantAdmin"),
    "compliance_officer_headers": build_user_headers(USER_IDS["COMPLIANCE_OFFICER"], "ComplianceOfficer"),
    "compliance_officer_2_headers": build_user_headers(USER_IDS["COMPLIANCE_OFFICER_2"], "ComplianceOfficer"),
    "auditor_headers": build_user_headers(USER_IDS["AUDITOR"], "Auditor"),
    "auditor_2_headers": build_user_headers(USER_IDS["AUDITOR_2"], "Auditor"),
    "order_clerk_headers": build_user_headers(USER_IDS["ORDER_CLERK"], "OrderClerk"),
    "fulfillment_clerk_headers": build_user_headers(USER_IDS["FULFILLMENT_CLERK"], "FulfillmentClerk"),
    "billing_clerk_headers": build_user_headers(USER_IDS["BILLING_CLERK"], "BillingClerk"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for an ad-hoc operator identity."""
    return build_user_headers(user_id, role)
