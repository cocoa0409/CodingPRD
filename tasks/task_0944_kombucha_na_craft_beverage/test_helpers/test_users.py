"""Pre-built role headers for every role the PRD declares.

Six of the seven roles carry an opaque identity, so a shared constant is the
canonical form for them. The seventh, `Subscriber`, is entity-backed: its
`X-User-ID` is the `id` of the acting `Subscription`, so it MUST be built per
instance with `make_subscriber_headers(subscription_id)`.

The three segregation-of-duties rules compare `X-User-ID` values directly, so
distinct actors of the same role are given distinct identifiers here.
"""

from prd_bench_local_runner.testing import build_user_headers

# Distinct operator identities. The segregation rules compare these values, so
# two ComplianceOfficers, two ProductionOperators and two QaManagers exist.
OPERATOR_USER_ID = "op-1"
OPERATOR_ALT_USER_ID = "op-2"
QA_USER_ID = "qa-1"
QA_ALT_USER_ID = "qa-2"
COMPLIANCE_SUBMITTER_USER_ID = "co-alice"
COMPLIANCE_APPROVER_USER_ID = "co-bob"
SALES_USER_ID = "sales-1"
SALES_ALT_USER_ID = "sales-2"
TAPROOM_USER_ID = "tap-1"
TAPROOM_ALT_USER_ID = "tap-2"
ADMIN_USER_ID = "admin-1"
ADMIN_ALT_USER_ID = "admin-2"


TEST_USERS = {
    "production_operator_headers": build_user_headers(OPERATOR_USER_ID, "ProductionOperator"),
    "production_operator_alt_headers": build_user_headers(
        OPERATOR_ALT_USER_ID, "ProductionOperator"
    ),
    "qa_manager_headers": build_user_headers(QA_USER_ID, "QaManager"),
    "qa_manager_alt_headers": build_user_headers(QA_ALT_USER_ID, "QaManager"),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_SUBMITTER_USER_ID, "ComplianceOfficer"
    ),
    "compliance_officer_approver_headers": build_user_headers(
        COMPLIANCE_APPROVER_USER_ID, "ComplianceOfficer"
    ),
    "sales_rep_headers": build_user_headers(SALES_USER_ID, "SalesRep"),
    "sales_rep_alt_headers": build_user_headers(SALES_ALT_USER_ID, "SalesRep"),
    "taproom_staff_headers": build_user_headers(TAPROOM_USER_ID, "TaproomStaff"),
    "taproom_staff_alt_headers": build_user_headers(TAPROOM_ALT_USER_ID, "TaproomStaff"),
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "platform_admin_alt_headers": build_user_headers(ADMIN_ALT_USER_ID, "PlatformAdmin"),
}


# --------------------------------------------------------------------------
# Per-instance builders
# --------------------------------------------------------------------------
def make_subscriber_headers(subscription_id: str) -> dict:
    """For the Subscriber role: X-User-ID is the id of the acting Subscription."""
    return build_user_headers(subscription_id, "Subscriber")


def make_production_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionOperator")


def make_qa_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QaManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_sales_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_taproom_staff_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TaproomStaff")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_headers(user_id: str, role: str) -> dict:
    return build_user_headers(user_id, role)
